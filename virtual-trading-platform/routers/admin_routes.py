import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import pymongo
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth import create_access_token, get_current_admin, get_current_token_payload, hash_password, verify_password
from db import get_db
from models import (
    AdminLogin,
    BalanceAdd,
    BalanceSet,
    InstrumentTypesUpdate,
    MarginUpdate,
    PasswordReset,
    SegmentUpdate,
    UserCreate,
    UserOut,
    LimitIncrease,
    BrokerageConfigCreate,
    BrokerageConfigItem,
)
from angelone_client import angel_client
from scrip_master import scrip_master, INDEX_CONFIGS, COMMODITY_CONFIGS
from mtm_engine import _close_single_trade

logger = logging.getLogger("virtual_trading_platform.admin_routes")
router = APIRouter(prefix="/admin", tags=["Super Admin Operations"])


# ---------------------------------------------------------------------------
# Helper: Centralized Audit Logging
# ---------------------------------------------------------------------------
async def log_audit_action(
    admin_id: str,
    action: str,
    target_user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Helper to insert an immutable audit record."""
    db = get_db()
    audit_entry = {
        "log_id": f"AUD-{uuid.uuid4().hex[:8].upper()}",
        "admin_id": admin_id,
        "action": action,
        "target_user_id": target_user_id,
        "details": details or {},
        "timestamp": datetime.now(timezone.utc),
    }
    try:
        await db.audit_logs.insert_one(audit_entry)
    except Exception as e:
        logger.error(f"Failed to write audit log for action {action}: {e}")


# ---------------------------------------------------------------------------
# 1. Admin Authentication
# ---------------------------------------------------------------------------
@router.post("/login")
async def admin_login(credentials: AdminLogin):
    """Super Admin login endpoint. Validates credentials and returns JWT."""
    db = get_db()
    admin_user = await db.users.find_one({"user_id": credentials.username, "role": "admin"})

    if not admin_user:
        # Fallback check against hardcoded / env default admin
        uname = (credentials.username or "").strip().lower()
        if (uname == "admin" and credentials.password == "admin123") or (uname in ("admin01", "admin") and credentials.password in ("AdminPassword123!", "admin123")):
            token = create_access_token(user_id="admin", role="admin")
            return {
                "status": "success",
                "access_token": token,
                "token_type": "bearer",
                "role": "admin",
                "user_id": "admin",
                "name": "Super Admin",
            }
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
        )

    if not verify_password(credentials.password, admin_user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
        )

    token = create_access_token(user_id=admin_user["user_id"], role="admin")
    return {
        "status": "success",
        "access_token": token,
        "token_type": "bearer",
        "role": "admin",
        "user_id": admin_user["user_id"],
        "name": admin_user.get("name", "Super Admin"),
    }


# ---------------------------------------------------------------------------
# 2. Trader Account Lifecycle (Create, List, Detail)
# ---------------------------------------------------------------------------
@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    admin_id: str = Depends(get_current_admin),
):
    """Creates a new trader account with allocated capital and permitted segments."""
    db = get_db()

    existing = await db.users.find_one({"user_id": body.user_id})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with user_id '{body.user_id}' already exists",
        )

    hashed_pw = hash_password(body.password)
    now = datetime.now(timezone.utc)

    user_doc = {
        "user_id": body.user_id,
        "name": body.name,
        "password_hash": hashed_pw,
        "allowed_segments": body.allowed_segments,
        "allowed_instrument_types": body.allowed_instrument_types or ["INDEX"],
        "is_active": True,
        "force_password_change": True,
        "created_by": admin_id,
        "created_at": now,
        "updated_at": now,
        "balance": body.balance,
        "available_balance": body.available_balance if body.available_balance != 0.0 else body.balance,
        "margin_blocked": body.margin_blocked,
        "realized_pnl": body.realized_pnl,
        "unrealized_pnl": body.unrealized_pnl,
        "equity": body.equity if body.equity != 0.0 else body.balance,
        "loss_pct": body.loss_pct,
        "auto_square_off_pct": body.auto_square_off_pct,
        "last_auto_square_off_at": None,
        "trade_limit": body.trade_limit,
        "trades_used": {"option": 0, "future": 0, "cash": 0},
    }

    try:
        await db.users.insert_one(user_doc)
    except pymongo.errors.DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with user_id '{body.user_id}' already exists",
        )

    await log_audit_action(
        admin_id=admin_id,
        action="USER_CREATE",
        target_user_id=body.user_id,
        details={"name": body.name, "allowed_segments": body.allowed_segments, "balance": body.balance},
    )

    user_doc.pop("password_hash", None)
    return UserOut(**user_doc)


@router.get("/users", response_model=List[UserOut])
async def list_users(
    low_balance_threshold: Optional[float] = Query(None, description="Filter users with loss_pct >= threshold (e.g. 70 for 70% loss)"),
    admin_id: str = Depends(get_current_admin),
):
    """List all registered users with live balance, margin, MTM equity, loss percentage, and computed risk level."""
    db = get_db()
    cursor = db.users.find({}, {"password_hash": 0, "_id": 0}).sort("created_at", pymongo.DESCENDING)
    users = await cursor.to_list(length=1000)

    result = []
    for u in users:
        balance = float(u.get("balance", 0.0))
        available_balance = float(u.get("available_balance", 0.0))
        margin_blocked = float(u.get("margin_blocked", 0.0))
        realized_pnl = float(u.get("realized_pnl", 0.0))
        unrealized_pnl = float(u.get("unrealized_pnl", 0.0))
        equity = float(u.get("equity", balance + realized_pnl + unrealized_pnl))
        loss_pct = float(u.get("loss_pct", 0.0))

        # Compute risk_level
        if loss_pct >= 80.0:
            risk_level = "critical"
        elif loss_pct >= 60.0:
            risk_level = "warning"
        else:
            risk_level = "normal"

        u["balance"] = balance
        u["available_balance"] = available_balance
        u["margin_blocked"] = margin_blocked
        u["realized_pnl"] = realized_pnl
        u["unrealized_pnl"] = unrealized_pnl
        u["equity"] = equity
        u["loss_pct"] = loss_pct
        u["risk_level"] = risk_level

        # Filter by low_balance_threshold if provided
        if low_balance_threshold is not None:
            if loss_pct < low_balance_threshold:
                continue

        result.append(u)

    return result


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user_detail(
    user_id: str,
    admin_id: str = Depends(get_current_admin),
):
    """Retrieve details of a single user."""
    db = get_db()
    user = await db.users.find_one({"user_id": user_id}, {"password_hash": 0, "_id": 0})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found")
    return user


# ---------------------------------------------------------------------------
# 3. Segment Administration & Password Management
# ---------------------------------------------------------------------------
@router.post("/users/{user_id}/segments")
@router.put("/users/{user_id}/segments")
async def update_user_segments(
    user_id: str,
    body: SegmentUpdate,
    admin_id: str = Depends(get_current_admin),
):
    """Update allowed segments (e.g. ['option', 'future']). Logs audited action 'SEGMENTS_UPDATE'."""
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found")

    old_segments = user.get("allowed_segments", [])
    now = datetime.now(timezone.utc)

    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "allowed_segments": body.allowed_segments,
                "updated_at": now,
            }
        },
    )

    await log_audit_action(
        admin_id=admin_id,
        action="SEGMENTS_UPDATE",
        target_user_id=user_id,
        details={"old_segments": old_segments, "new_segments": body.allowed_segments},
    )

    return {
        "status": "success",
        "user_id": user_id,
        "old_segments": old_segments,
        "new_segments": body.allowed_segments,
    }


@router.put("/users/{user_id}/instrument-types")
async def update_user_instrument_types(
    user_id: str,
    data: InstrumentTypesUpdate,
    admin_id: str = Depends(get_current_admin),
):
    """Update permitted instrument types (e.g. ['INDEX', 'MCX']). Logs audited action 'INSTRUMENT_TYPES_UPDATE'."""
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with user_id '{user_id}' not found",
        )

    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "allowed_instrument_types": data.allowed_instrument_types,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    await log_audit_action(
        admin_id=admin_id,
        action="INSTRUMENT_TYPES_UPDATE",
        target_user_id=user_id,
        details={"allowed_instrument_types": data.allowed_instrument_types},
    )

    return {
        "status": "success",
        "message": f"Allowed instrument types for user {user_id} updated to {data.allowed_instrument_types}",
        "user_id": user_id,
        "allowed_instrument_types": data.allowed_instrument_types,
    }


@router.post("/users/{user_id}/limit-increase")
async def limit_increase(
    user_id: str,
    data: LimitIncrease,
    admin_id: str = Depends(get_current_admin),
):
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    segment = data.segment or "option"
    new_limit = data.new_limit if data.new_limit is not None else 0
    await db.users.update_one({"user_id": user_id}, {"$set": {f"trade_limit.{segment}": new_limit}})
    await log_audit_action(
        admin_id=admin_id,
        action="LIMIT_INCREASE",
        target_user_id=user_id,
        details={"segment": segment, "new_limit": new_limit},
    )
    return {"status": "success", "action": "LIMIT_INCREASE", "user_id": user_id, "segment": segment, "new_limit": new_limit}


@router.post("/users/{user_id}/limit-revoke")
async def limit_revoke(
    user_id: str,
    data: LimitIncrease,
    admin_id: str = Depends(get_current_admin),
):
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    segment = data.segment or "option"
    new_limit = data.new_limit if data.new_limit is not None else 0
    await db.users.update_one({"user_id": user_id}, {"$set": {f"trade_limit.{segment}": new_limit}})
    await log_audit_action(
        admin_id=admin_id,
        action="LIMIT_REVOKE",
        target_user_id=user_id,
        details={"segment": segment, "new_limit": new_limit},
    )
    return {"status": "success", "action": "LIMIT_REVOKE", "user_id": user_id, "segment": segment, "new_limit": new_limit}


@router.post("/users/{user_id}/reset-password")
@router.put("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    body: Optional[PasswordReset] = None,
    admin_id: str = Depends(get_current_admin),
):
    """Direct administrative password reset. Forces password change upon user's next login."""
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found")

    raw_password = body.new_password if body and body.new_password else f"VTrade@{uuid.uuid4().hex[:6]}"
    hashed_pw = hash_password(raw_password)
    now = datetime.now(timezone.utc)

    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "password_hash": hashed_pw,
                "force_password_change": True,
                "updated_at": now,
            }
        },
    )

    await log_audit_action(
        admin_id=admin_id,
        action="PASSWORD_RESET",
        target_user_id=user_id,
        details={"forced_reset": True},
    )

    return {
        "status": "success",
        "user_id": user_id,
        "temp_password": raw_password,
        "message": f"Password reset for user '{user_id}'. Trader must change password upon next login.",
    }


# ---------------------------------------------------------------------------
# 4. User Trade Book Inspection
# ---------------------------------------------------------------------------
@router.get("/users/{user_id}/trades")
async def get_user_trades_for_admin(
    user_id: str,
    segment: Optional[str] = Query(None, description="option, future, or cash"),
    admin_id: str = Depends(get_current_admin),
):
    """Retrieve full trade audit history across segments for a specific trader."""
    db = get_db()
    segments = [segment.lower()] if segment else ["option", "future", "cash"]
    all_trades = []

    for seg in segments:
        if seg not in ("option", "future", "cash"):
            continue
        coll = db[f"trades_{seg}"]
        cursor = coll.find({"user_id": user_id}, {"_id": 0}).sort("entry_time", pymongo.DESCENDING)
        trades = await cursor.to_list(length=500)
        all_trades.extend(trades)

    return {
        "status": "success",
        "user_id": user_id,
        "count": len(all_trades),
        "trades": all_trades,
    }


# ---------------------------------------------------------------------------
# 5. Emergency Administrative Square-Off (Force Close All Trades)
# ---------------------------------------------------------------------------
@router.post("/users/{user_id}/force-close-all")
async def force_close_all_user_trades(
    user_id: str,
    admin_id: str = Depends(get_current_admin),
):
    """Emergency square-off endpoint: Forces immediate closure of ALL active open positions
    across Options, Futures, and Cash for the target trader.
    """
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found")

    segments = ["option", "future", "cash"]
    closed_summary = {"total_closed": 0, "option": 0, "future": 0, "cash": 0, "trades": [], "cancelled_pending_orders": 0}

    from order_engine import cancel_all_user_pending_orders
    closed_summary["cancelled_pending_orders"] = await cancel_all_user_pending_orders(
        user_id=user_id,
        cancelled_by=f"ADMIN_FORCE_CLOSE_{admin_id}",
    )

    for seg in segments:
        coll = db[f"trades_{seg}"]
        open_trades = await coll.find({"user_id": user_id, "status": "OPEN"}).to_list(length=1000)

        for trade in open_trades:
            try:
                exit_price = angel_client.get_ltp(
                    exchange=trade.get("exchange", "NSE"),
                    tradingsymbol=trade.get("tradingsymbol", trade.get("instrument")),
                    symboltoken=trade.get("symboltoken", ""),
                )
            except Exception as e:
                logger.warning(f"Could not fetch exit LTP for trade {trade['trade_id']}, using entry: {e}")
                exit_price = float(trade.get("entry_price", 0.0))

            closed_trade = await _close_single_trade(
                segment=seg,
                trade=trade,
                exit_price=exit_price,
                closed_by=f"ADMIN_FORCE_CLOSE_{admin_id}",
            )

            if closed_trade:
                closed_summary[seg] += 1
                closed_summary["total_closed"] += 1
                closed_summary["trades"].append({
                    "trade_id": trade["trade_id"],
                    "segment": seg,
                    "pnl": closed_trade.get("pnl", 0.0),
                    "exit_price": exit_price,
                })

    await log_audit_action(
        admin_id=admin_id,
        action="FORCE_CLOSE_ALL",
        target_user_id=user_id,
        details={"total_closed": closed_summary["total_closed"], "segments": {s: closed_summary[s] for s in segments}},
    )

    return {
        "status": "success",
        "message": f"Force-closed {closed_summary['total_closed']} open trades for user '{user_id}'",
        "summary": closed_summary,
    }


# ---------------------------------------------------------------------------
# 6. Audit Log Inspector
# ---------------------------------------------------------------------------
@router.get("/audit-logs")
async def get_audit_logs(
    target_user_id: Optional[str] = Query(None),
    admin_id: str = Depends(get_current_admin),
):
    """Retrieve system administrative audit logs."""
    db = get_db()
    query: Dict[str, Any] = {}
    if target_user_id:
        query["target_user_id"] = target_user_id

    cursor = db.audit_logs.find(query, {"_id": 0}).sort("timestamp", pymongo.DESCENDING)
    logs = await cursor.to_list(length=500)
    return {"status": "success", "count": len(logs), "audit_logs": logs}


# ---------------------------------------------------------------------------
# 7. Balance & Margin Management
# ---------------------------------------------------------------------------
class ThresholdUpdate(BaseModel):
    threshold_pct: float = Field(..., ge=1.0, le=100.0, description="Auto square-off loss percentage threshold (e.g. 80.0)")


@router.put("/users/{user_id}/balance/set")
async def set_user_balance(
    user_id: str,
    body: BalanceSet,
    admin_id: str = Depends(get_current_admin),
):
    """Set exact allocated balance and recompute available balance."""
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found")

    margin_blocked = float(user.get("margin_blocked", 0.0))
    realized_pnl = float(user.get("realized_pnl", 0.0))
    old_balance = float(user.get("balance", 0.0))
    old_available = float(user.get("available_balance", 0.0))
    new_balance = float(body.balance)

    if new_balance < margin_blocked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot set balance (₹{new_balance:,.2f}) below currently locked margin (₹{margin_blocked:,.2f}) in open trades",
        )

    new_available = new_balance - margin_blocked + realized_pnl
    now = datetime.now(timezone.utc)

    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "balance": new_balance,
                "available_balance": new_available,
                "updated_at": now,
            }
        },
    )

    await log_audit_action(
        admin_id=admin_id,
        action="BALANCE_SET",
        target_user_id=user_id,
        details={
            "old_balance": old_balance,
            "new_balance": new_balance,
            "old_available": old_available,
            "new_available": new_available,
            "margin_blocked": margin_blocked,
            "realized_pnl": realized_pnl,
        },
    )

    return {
        "status": "success",
        "user_id": user_id,
        "balance": new_balance,
        "available_balance": new_available,
        "margin_blocked": margin_blocked,
        "realized_pnl": realized_pnl,
    }


@router.put("/users/{user_id}/balance/add")
async def add_user_balance(
    user_id: str,
    body: BalanceAdd,
    admin_id: str = Depends(get_current_admin),
):
    """Add or subtract balance from both balance and available_balance atomically."""
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found")

    old_balance = float(user.get("balance", 0.0))
    old_available = float(user.get("available_balance", 0.0))
    amount = float(body.amount)

    new_available = old_available + amount
    new_balance = old_balance + amount

    if new_available < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Operation would result in negative available balance (₹{new_available:,.2f}). Current available: ₹{old_available:,.2f}",
        )
    if new_balance < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Operation would result in negative allocated balance (₹{new_balance:,.2f}). Current balance: ₹{old_balance:,.2f}",
        )

    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$inc": {"balance": amount, "available_balance": amount},
            "$set": {"updated_at": now},
        },
    )

    await log_audit_action(
        admin_id=admin_id,
        action="BALANCE_ADD",
        target_user_id=user_id,
        details={
            "amount": amount,
            "old_balance": old_balance,
            "new_balance": new_balance,
            "old_available": old_available,
            "new_available": new_available,
        },
    )

    return {
        "status": "success",
        "user_id": user_id,
        "amount_added": amount,
        "balance": new_balance,
        "available_balance": new_available,
    }


@router.put("/users/{user_id}/auto-square-off-threshold")
async def update_auto_square_off_threshold(
    user_id: str,
    body: ThresholdUpdate,
    admin_id: str = Depends(get_current_admin),
):
    """Update user's auto-square-off loss threshold percentage."""
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found")

    old_pct = float(user.get("auto_square_off_pct", 80.0))
    new_pct = float(body.threshold_pct)
    now = datetime.now(timezone.utc)

    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"auto_square_off_pct": new_pct, "updated_at": now}},
    )

    await log_audit_action(
        admin_id=admin_id,
        action="THRESHOLD_UPDATE",
        target_user_id=user_id,
        details={"old_threshold_pct": old_pct, "new_threshold_pct": new_pct},
    )

    return {
        "status": "success",
        "user_id": user_id,
        "old_threshold_pct": old_pct,
        "auto_square_off_pct": new_pct,
    }




# ---------------------------------------------------------------------------
# 4. Instrument & Margin Management
# ---------------------------------------------------------------------------
@router.get("/instruments/future-list")
async def get_future_instruments_list(
    caller: Dict[str, Any] = Depends(get_current_token_payload),
):
    """Retrieve all FUTURE segment instruments with live LTP sourced directly from Scrip Master and margin configs."""
    db = get_db()
    scrip_master.ensure_loaded()

    # Fetch margin configurations from DB (keyed by symbol + segment)
    margins_cursor = db.instrument_margins.find({"segment": "future"}, {"_id": 0})
    margins_list = await margins_cursor.to_list(length=500)
    margins_map = {m["symbol"].upper(): m for m in margins_list}

    # Fetch DB overrides for commodity configs (if admin enabled/disabled)
    comm_overrides_cursor = db.commodity_configs.find({}, {"_id": 0})
    comm_overrides_list = await comm_overrides_cursor.to_list(length=100)
    comm_overrides_map = {c["name"].upper(): c for c in comm_overrides_list}

    results = []
    contract_pairs = []

    # 1. Index Futures
    for sym, cfg in INDEX_CONFIGS.items():
        expiries = scrip_master.get_expiries(sym, "future")
        running_expiry_obj = expiries[0] if expiries else None
        running_expiry = running_expiry_obj["expiry"] if running_expiry_obj else None
        formatted_expiry = running_expiry_obj.get("formatted_date", running_expiry) if running_expiry_obj else "No Expiry"

        contract = scrip_master.find_contract(sym, "future", expiry=running_expiry) if running_expiry else None
        margin_doc = margins_map.get(sym.upper())
        margin_required = float(margin_doc["margin_required"]) if margin_doc and "margin_required" in margin_doc and margin_doc["margin_required"] is not None else None
        lot_size = contract.get("lot_size", cfg.get("default_lot", 25)) if contract else cfg.get("default_lot", 25)

        item = {
            "symbol": sym,
            "display_name": sym,
            "tradingsymbol": contract["tradingsymbol"] if contract else f"{sym} FUT",
            "expiry": formatted_expiry,
            "exchange": cfg.get("exch_seg", "NFO" if sym != "SENSEX" else "BFO"),
            "symboltoken": str(contract["symboltoken"]) if contract else "0",
            "lot_size": lot_size,
            "ltp": None,
            "ltp_status": "Live" if contract else "Contract Unavailable",
            "margin_required": margin_required,
            "instrument_type": "INDEX",
            "multiplier": lot_size,
            "quote_unit": "₹/pt",
            "enabled": True,
            "updated_at": margin_doc.get("updated_at").isoformat() if margin_doc and isinstance(margin_doc.get("updated_at"), datetime) else str(margin_doc.get("updated_at")) if margin_doc and margin_doc.get("updated_at") else None,
        }
        results.append(item)
        if contract:
            contract_pairs.append((item, contract))

    # 2. MCX Commodity Futures
    for sym, cfg in COMMODITY_CONFIGS.items():
        override = comm_overrides_map.get(sym.upper(), {})
        enabled = override.get("enabled", cfg.get("enabled", False))
        mult = override.get("pnl_multiplier_per_lot", cfg.get("pnl_multiplier_per_lot"))
        quote_unit = cfg.get("quote_unit", "₹/unit")

        expiries = scrip_master.get_expiries(sym, "future")
        running_expiry_obj = expiries[0] if expiries else None
        running_expiry = running_expiry_obj["expiry"] if running_expiry_obj else None
        formatted_expiry = running_expiry_obj.get("formatted_date", running_expiry) if running_expiry_obj else "No Expiry"

        contract = scrip_master.find_contract(sym, "future", expiry=running_expiry) if running_expiry else None
        margin_doc = margins_map.get(sym.upper())
        margin_required = float(margin_doc["margin_required"]) if margin_doc and "margin_required" in margin_doc and margin_doc["margin_required"] is not None else None
        lot_size = contract.get("lot_size", cfg.get("default_lot", 1)) if contract else cfg.get("default_lot", 1)

        item = {
            "symbol": sym,
            "display_name": cfg.get("display_name", sym),
            "tradingsymbol": contract["tradingsymbol"] if contract else f"{sym} FUT",
            "expiry": formatted_expiry,
            "exchange": "MCX",
            "symboltoken": str(contract["symboltoken"]) if contract else "0",
            "lot_size": lot_size,
            "ltp": None,
            "ltp_status": "Disabled" if not enabled else ("Live" if contract else "Contract Unavailable"),
            "margin_required": margin_required,
            "instrument_type": "MCX",
            "multiplier": mult,
            "quote_unit": quote_unit,
            "enabled": enabled,
            "updated_at": margin_doc.get("updated_at").isoformat() if margin_doc and isinstance(margin_doc.get("updated_at"), datetime) else str(margin_doc.get("updated_at")) if margin_doc and margin_doc.get("updated_at") else None,
        }
        results.append(item)
        if enabled and contract:
            contract_pairs.append((item, contract))

    async def _fetch_single_ltp(target_item: Dict[str, Any], target_contract: Dict[str, Any]):
        try:
            val = await asyncio.to_thread(
                angel_client.get_ltp,
                exchange=target_contract["exchange"],
                tradingsymbol=target_contract["tradingsymbol"],
                symboltoken=target_contract["symboltoken"],
                max_age_seconds=60.0,
            )
            target_item["ltp"] = val
            target_item["ltp_status"] = "Live"
        except Exception as ex:
            logger.warning(f"Could not fetch live LTP for future {target_item.get('symbol')}: {ex}")
            target_item["ltp"] = None
            target_item["ltp_status"] = "Price Unavailable"

    if contract_pairs:
        await asyncio.gather(*[_fetch_single_ltp(it, ct) for it, ct in contract_pairs])

    return results


@router.put("/instruments/{symbol}/{segment}/margin")
async def update_instrument_margin(
    symbol: str,
    segment: str,
    margin_data: MarginUpdate,
    admin_id: str = Depends(get_current_admin),
):
    """Set or update margin required per lot for a specific instrument and segment."""
    symbol_upper = symbol.upper()
    segment_lower = segment.lower()

    if segment_lower != "future":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Margin configuration is currently only applicable to the 'future' segment. Received: '{segment_lower}'.",
        )

    db = get_db()
    now = datetime.now(timezone.utc)
    margin_value = float(margin_data.margin_required)

    await db.instrument_margins.update_one(
        {"symbol": symbol_upper, "segment": segment_lower},
        {
            "$set": {
                "symbol": symbol_upper,
                "segment": segment_lower,
                "margin_required": margin_value,
                "updated_at": now,
                "updated_by": admin_id,
            }
        },
        upsert=True,
    )

    await log_audit_action(
        admin_id=admin_id,
        action="UPDATE_MARGIN_REQUIREMENT",
        details={
            "symbol": symbol_upper,
            "segment": segment_lower,
            "margin_required": margin_value,
        },
    )

    return {
        "status": "success",
        "message": f"Margin requirement for {symbol_upper} ({segment_lower}) updated to ₹{margin_value:,.2f}",
        "symbol": symbol_upper,
        "segment": segment_lower,
        "margin_required": margin_value,
        "updated_at": now.isoformat(),
    }


@router.get("/instruments/margins")
async def get_all_margins(
    admin_id: str = Depends(get_current_admin),
):
    """Get all configured instrument margin requirements."""
    db = get_db()
    cursor = db.instrument_margins.find({}, {"_id": 0})
    margins = await cursor.to_list(length=100)
    return {"status": "success", "count": len(margins), "margins": margins}


# ─────────────────────────────────────────────────────────────────────────────
# DELETE USER
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin_id: str = Depends(get_current_admin),
):
    """
    Permanently delete a trader account and ALL associated data:
    - User document
    - All trades across option / future / cash collections
    - All audit log entries referencing this user
    """
    db = get_db()

    # Confirm the user exists
    existing = await db.users.find_one({"user_id": user_id})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found.",
        )

    # Prevent admin from deleting themselves
    if user_id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own admin account.",
        )

    now = datetime.now(timezone.utc)

    # Write audit log BEFORE deletion so the event is preserved
    await log_audit_action(
        admin_id=admin_id,
        action="DELETE_USER",
        target_user_id=user_id,
        details={
            "name": existing.get("name", ""),
            "balance": existing.get("balance", 0),
            "deleted_at": now.isoformat(),
        },
    )

    # Delete all trades across all segments
    deleted_trades = {}
    for seg in ("option", "future", "cash"):
        result = await db[f"trades_{seg}"].delete_many({"user_id": user_id})
        deleted_trades[seg] = result.deleted_count

    # Delete the user document
    await db.users.delete_one({"user_id": user_id})

    return {
        "status": "success",
        "message": f"User '{user_id}' and all associated data permanently deleted.",
        "deleted_trades": deleted_trades,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RESET USER ACCOUNT (Wipe trades, restore balance to original)
# ─────────────────────────────────────────────────────────────────────────────

class ResetAccountRequest(BaseModel):
    new_balance: float = 100000.0  # Optional: reset to this balance (default 1 lakh)


@router.post("/users/{user_id}/reset-account")
async def reset_user_account(
    user_id: str,
    body: ResetAccountRequest = ResetAccountRequest(),
    admin_id: str = Depends(get_current_admin),
):
    """
    Reset a trader's account to a clean slate:
    1. Force-close any remaining OPEN trades at current entry price (no PnL impact).
    2. Hard-delete ALL trades (open + closed) from option / future / cash collections.
    3. Reset user's financial fields: balance, available_balance, margin_blocked,
       realized_pnl, unrealized_pnl, equity, loss_pct all back to a fresh state.
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    existing = await db.users.find_one({"user_id": user_id})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found.",
        )

    new_balance = float(body.new_balance)
    if new_balance < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset balance must be >= 0.",
        )

    # Count trades being wiped for audit log
    trade_counts = {}
    for seg in ("option", "future", "cash"):
        count = await db[f"trades_{seg}"].count_documents({"user_id": user_id})
        trade_counts[seg] = count

    # Hard-delete ALL trades and orders for this user
    for seg in ("option", "future", "cash"):
        await db[f"trades_{seg}"].delete_many({"user_id": user_id})
    await db.orders.delete_many({"user_id": user_id})

    # Reset user financial fields to clean slate
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "balance": new_balance,
                "available_balance": new_balance,
                "margin_blocked": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "equity": new_balance,
                "loss_pct": 0.0,
                "last_auto_square_off_at": None,
                "updated_at": now,
            }
        },
    )

    await log_audit_action(
        admin_id=admin_id,
        action="RESET_USER_ACCOUNT",
        target_user_id=user_id,
        details={
            "trades_deleted": trade_counts,
            "new_balance": new_balance,
            "reset_at": now.isoformat(),
        },
    )

    return {
        "status": "success",
        "message": f"Account for '{user_id}' has been fully reset. All trades wiped, balance restored to ₹{new_balance:,.2f}.",
        "new_balance": new_balance,
        "trades_deleted": trade_counts,
    }


# ---------------------------------------------------------------------------
# 17. Brokerage Management
# ---------------------------------------------------------------------------
@router.get("/brokerage")
async def get_brokerage_configs(
    scope: Optional[str] = Query(None, description="'global' or 'user'"),
    user_id: Optional[str] = Query(None, description="Optional filter by user_id"),
    admin_id: str = Depends(get_current_admin),
):
    """Retrieve brokerage configurations (global or user specific)."""
    db = get_db()
    query: Dict[str, Any] = {}
    if scope:
        query["scope"] = scope
    if user_id:
        query["user_id"] = user_id
    cursor = db.brokerage_config.find(query, {"_id": 0}).sort("segment", pymongo.ASCENDING)
    configs = await cursor.to_list(length=200)
    return {"status": "success", "count": len(configs), "configs": configs}


@router.put("/brokerage")
async def set_global_brokerage_config(
    body: BrokerageConfigCreate,
    admin_id: str = Depends(get_current_admin),
):
    """Create or update a global brokerage configuration."""
    db = get_db()
    now = datetime.now(timezone.utc)
    itype = (body.instrument_type or "any").upper()
    seg = body.segment.lower()

    query = {
        "scope": "global",
        "segment": seg,
        "instrument_type": itype,
    }
    before = await db.brokerage_config.find_one(query, {"_id": 0})
    update_doc = {
        "scope": "global",
        "user_id": None,
        "segment": seg,
        "instrument_type": itype,
        "mode": body.mode,
        "value": float(body.value),
        "enabled": body.enabled,
        "updated_by": admin_id,
        "updated_at": now,
    }
    await db.brokerage_config.update_one(query, {"$set": update_doc}, upsert=True)
    after = await db.brokerage_config.find_one(query, {"_id": 0})

    await log_audit_action(
        admin_id=admin_id,
        action="SET_GLOBAL_BROKERAGE_CONFIG",
        details={
            "before": before,
            "after": after,
            "scope": "global",
            "segment": seg,
            "instrument_type": itype,
        },
    )
    return {"status": "success", "config": after}


@router.put("/users/{user_id}/brokerage")
async def set_user_brokerage_config(
    user_id: str,
    body: BrokerageConfigCreate,
    admin_id: str = Depends(get_current_admin),
):
    """Create or update a user-specific brokerage configuration override."""
    db = get_db()
    existing_user = await db.users.find_one({"user_id": user_id})
    if not existing_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found.",
        )
    now = datetime.now(timezone.utc)
    itype = (body.instrument_type or "any").upper()
    seg = body.segment.lower()

    query = {
        "scope": "user",
        "user_id": user_id,
        "segment": seg,
        "instrument_type": itype,
    }
    before = await db.brokerage_config.find_one(query, {"_id": 0})
    update_doc = {
        "scope": "user",
        "user_id": user_id,
        "segment": seg,
        "instrument_type": itype,
        "mode": body.mode,
        "value": float(body.value),
        "enabled": body.enabled,
        "updated_by": admin_id,
        "updated_at": now,
    }
    await db.brokerage_config.update_one(query, {"$set": update_doc}, upsert=True)
    after = await db.brokerage_config.find_one(query, {"_id": 0})

    await log_audit_action(
        admin_id=admin_id,
        action="SET_USER_BROKERAGE_CONFIG",
        target_user_id=user_id,
        details={
            "before": before,
            "after": after,
            "scope": "user",
            "segment": seg,
            "instrument_type": itype,
        },
    )
    return {"status": "success", "config": after}


@router.delete("/users/{user_id}/brokerage")
async def delete_user_brokerage_config(
    user_id: str,
    segment: str = Query(..., description="Segment to delete override for"),
    instrument_type: str = Query("any", description="Instrument type (INDEX, MCX, any)"),
    admin_id: str = Depends(get_current_admin),
):
    """Delete a user-specific brokerage configuration override."""
    db = get_db()
    seg = segment.lower()
    itype = (instrument_type or "any").upper()

    query = {
        "scope": "user",
        "user_id": user_id,
        "segment": seg,
        "instrument_type": {"$in": [itype, itype.lower()]},
    }
    before = await db.brokerage_config.find_one(query, {"_id": 0})
    if not before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user brokerage override found for user '{user_id}' on segment '{seg}' and type '{itype}'.",
        )

    res = await db.brokerage_config.delete_one(query)

    await log_audit_action(
        admin_id=admin_id,
        action="DELETE_USER_BROKERAGE_CONFIG",
        target_user_id=user_id,
        details={
            "before": before,
            "deleted_count": res.deleted_count,
        },
    )
    return {
        "status": "success",
        "message": f"Brokerage override removed for user '{user_id}'.",
        "deleted_count": res.deleted_count,
    }


@router.get("/brokerage/summary")
async def get_brokerage_summary(
    user_id: Optional[str] = Query(None, description="Filter summary by user_id"),
    segment: Optional[str] = Query(None, description="Filter summary by segment"),
    start_date: Optional[str] = Query(None, description="ISO format start date"),
    end_date: Optional[str] = Query(None, description="ISO format end date"),
    admin_id: str = Depends(get_current_admin),
):
    """Aggregate total brokerage collected across all closed and open trades."""
    db = get_db()
    segments = [segment.lower()] if segment else ["option", "future", "cash"]

    total_entry = 0.0
    total_exit = 0.0
    total_collected = 0.0
    trades_count = 0
    by_segment: Dict[str, Any] = {s: {"entry": 0.0, "exit": 0.0, "total": 0.0, "trades": 0} for s in ["option", "future", "cash"]}
    by_user: Dict[str, Any] = {}

    date_filter: Dict[str, Any] = {}
    if start_date:
        try:
            date_filter["$gte"] = datetime.fromisoformat(start_date)
        except Exception:
            pass
    if end_date:
        try:
            date_filter["$lte"] = datetime.fromisoformat(end_date)
        except Exception:
            pass

    for seg in segments:
        q: Dict[str, Any] = {}
        if user_id:
            q["user_id"] = user_id
        if date_filter:
            q["entry_time"] = date_filter

        cursor = db[f"trades_{seg}"].find(q)
        async for t in cursor:
            e_brok = float(t.get("entry_brokerage", 0.0) or 0.0)
            x_brok = float(t.get("exit_brokerage", 0.0) or 0.0)
            t_total = float(t.get("brokerage_total", round(e_brok + x_brok, 2)) or 0.0)

            total_entry += e_brok
            total_exit += x_brok
            total_collected += t_total
            trades_count += 1

            if seg in by_segment:
                by_segment[seg]["entry"] = round(by_segment[seg]["entry"] + e_brok, 2)
                by_segment[seg]["exit"] = round(by_segment[seg]["exit"] + x_brok, 2)
                by_segment[seg]["total"] = round(by_segment[seg]["total"] + t_total, 2)
                by_segment[seg]["trades"] += 1

            u_id = t.get("user_id", "unknown")
            if u_id not in by_user:
                by_user[u_id] = {"entry": 0.0, "exit": 0.0, "total": 0.0, "trades": 0}
            by_user[u_id]["entry"] = round(by_user[u_id]["entry"] + e_brok, 2)
            by_user[u_id]["exit"] = round(by_user[u_id]["exit"] + x_brok, 2)
            by_user[u_id]["total"] = round(by_user[u_id]["total"] + t_total, 2)
            by_user[u_id]["trades"] += 1

    return {
        "status": "success",
        "total_brokerage_collected": round(total_collected, 2),
        "total_entry_brokerage": round(total_entry, 2),
        "total_exit_brokerage": round(total_exit, 2),
        "total_trades_charged": trades_count,
        "by_segment": by_segment,
        "by_user": by_user,
    }


# ---------------------------------------------------------------------------
# 18. Order Management (Pending / Limit Orders)
# ---------------------------------------------------------------------------
@router.get("/users/{user_id}/orders")
async def get_user_orders_admin(
    user_id: str,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (PENDING, EXECUTED, CANCELLED, REJECTED)"),
    admin_id: str = Depends(get_current_admin),
):
    """Retrieve orders for a specific user."""
    db = get_db()
    q: Dict[str, Any] = {"user_id": user_id}
    if status_filter:
        q["status"] = status_filter.upper()

    cursor = db.orders.find(q, {"_id": 0}).sort("created_at", pymongo.DESCENDING)
    orders = await cursor.to_list(length=500)
    return {
        "status": "success",
        "user_id": user_id,
        "count": len(orders),
        "orders": orders,
    }


@router.post("/users/{user_id}/orders/{order_id}/cancel")
async def cancel_order_admin(
    user_id: str,
    order_id: str,
    admin_id: str = Depends(get_current_admin),
):
    """Cancel a pending user order by Admin, releasing reserved margin & brokerage."""
    db = get_db()
    now_utc = datetime.now(timezone.utc)

    claimed = await db.orders.find_one_and_update(
        {"order_id": order_id, "user_id": user_id, "status": "PENDING"},
        {
            "$set": {
                "status": "CANCELLED",
                "cancelled_by": f"ADMIN_{admin_id}",
                "modified_at": now_utc,
            },
            "$inc": {"version": 1},
            "$push": {
                "history": {
                    "action": "ADMIN_CANCEL",
                    "admin_id": admin_id,
                    "timestamp": now_utc,
                }
            },
        },
        return_document=pymongo.ReturnDocument.AFTER,
    )

    if not claimed:
        existing = await db.orders.find_one({"order_id": order_id, "user_id": user_id})
        current_status = existing.get("status") if existing else "NOT_FOUND"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order cannot be cancelled (current status: {current_status})",
        )

    reserved = float(claimed.get("reserved_total", 0.0))
    if reserved > 0:
        await db.users.update_one(
            {"user_id": user_id},
            {
                "$inc": {
                    "available_balance": reserved,
                    "margin_blocked": -reserved,
                },
                "$set": {"updated_at": now_utc},
            },
        )

    await log_audit_action(
        admin_id=admin_id,
        action="ADMIN_CANCEL_ORDER",
        target_user_id=user_id,
        details={
            "order_id": order_id,
            "refunded_reserved": reserved,
        },
    )

    claimed.pop("_id", None)
    return {
        "status": "success",
        "message": f"Order {order_id} cancelled by admin, refunded ₹{reserved:,.2f}",
        "order": claimed,
    }


