import logging
import uuid
import pymongo
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo import ReturnDocument

from auth import create_access_token, get_current_user, hash_password, verify_password
from db import get_db
from models import (
    PasswordChange,
    TradeCashCreate,
    TradeFutureCreate,
    TradeOptionCreate,
    UserLogin,
    BrokeragePreviewOut,
    OrderCreate,
    OrderModify,
    OrderOut,
)
from angelone_client import LTPFetchError, angel_client
from mtm_engine import _close_single_trade
from scrip_master import scrip_master
import market_calendar
from trade_engine import (
    resolve_contract,
    compute_required_lock,
    open_position,
    resolve_brokerage_config,
    compute_brokerage,
)

logger = logging.getLogger("virtual_trading_platform.user_routes")
router = APIRouter(prefix="/user", tags=["Trader User Operations"])


# ---------------------------------------------------------------------------
# 1. Authentication & Password Lifecycle
# ---------------------------------------------------------------------------
@router.post("/login")
async def user_login(credentials: UserLogin):
    """Trader User login endpoint.
    Returns JWT access_token and force_password_change flag.
    """
    db = get_db()
    user = await db.users.find_one({"user_id": credentials.user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID or password",
        )

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Please contact your administrator.",
        )

    if not verify_password(credentials.password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID or password",
        )

    token = create_access_token(user_id=user["user_id"], role="user")
    force_change = user.get("force_password_change", False)

    return {
        "status": "success",
        "access_token": token,
        "token_type": "bearer",
        "user_id": user["user_id"],
        "name": user.get("name", ""),
        "role": "user",
        "force_password_change": force_change,
        "allowed_segments": user.get("allowed_segments", []),
        "allowed_instrument_types": user.get("allowed_instrument_types", ["INDEX"]),
    }


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    user_id: str = Depends(get_current_user),
):
    """Allows user to change their password upon old password verification.
    Clears the force_password_change flag.
    """
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not verify_password(data.old_password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password verification failed",
        )

    new_hash = hash_password(data.new_password)
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "password_hash": new_hash,
                "force_password_change": False,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    return {"status": "success", "message": "Password changed successfully"}


# ---------------------------------------------------------------------------
# 2. Instruments & Contract Chains
# ---------------------------------------------------------------------------
@router.get("/instruments")
async def get_allowed_instruments(user_id: str = Depends(get_current_user)):
    """Fetch instruments relevant to the user's allowed segments."""
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    allowed_segments = user.get("allowed_segments", [])
    cursor = db.instruments.find(
        {"segment": {"$in": allowed_segments}},
        {"_id": 0}
    ).sort("symbol", pymongo.ASCENDING)

    instruments = await cursor.to_list(length=500)

    # Attach margin configs
    margins_cursor = db.instrument_margins.find({}, {"_id": 0})
    margins_list = await margins_cursor.to_list(length=500)
    margins_map = {(m["symbol"].upper(), m["segment"].lower()): float(m["margin_required"]) for m in margins_list if "margin_required" in m}

    for inst in instruments:
        sym = inst.get("symbol", "").upper()
        seg = inst.get("segment", "").lower()
        if (sym, seg) in margins_map:
            inst["margin_required"] = margins_map[(sym, seg)]
        elif seg == "future":
            inst["margin_required"] = 100000.0

    return {
        "status": "success",
        "allowed_segments": allowed_segments,
        "count": len(instruments),
        "instruments": instruments,
    }


@router.get("/instruments/future-list")
async def get_user_future_instruments_list(user_id: str = Depends(get_current_user)):
    """Retrieve all FUTURE segment instruments with live LTP and margin configs for trading."""
    from routers.admin_routes import get_future_instruments_list
    return await get_future_instruments_list(caller={"user_id": user_id, "role": "user"})


@router.get("/instruments/{symbol}/{segment}/margin")
async def get_instrument_margin(
    symbol: str,
    segment: str,
    user_id: str = Depends(get_current_user),
):
    """Retrieve margin requirement for a specific instrument and segment."""
    db = get_db()
    sym = symbol.upper()
    seg = segment.lower()
    margin_doc = await db.instrument_margins.find_one(
        {"symbol": sym, "segment": seg},
        {"_id": 0}
    )
    inst_type = scrip_master.get_instrument_type(sym)
    if margin_doc and "margin_required" in margin_doc and margin_doc["margin_required"] is not None:
        margin_required = float(margin_doc["margin_required"])
        is_configured = True
    else:
        if inst_type == "MCX":
            margin_required = None
            is_configured = False
        else:
            defaults = {"future": 100000.0, "option": 50000.0, "cash": 0.0}
            margin_required = defaults.get(seg, 100000.0)
            is_configured = False

    return {
        "status": "success",
        "symbol": sym,
        "segment": seg,
        "instrument_type": inst_type,
        "margin_required": margin_required,
        "is_configured": is_configured,
    }


@router.get("/contracts/chain")
async def get_contract_chain(
    symbol: str = Query("NIFTY", description="Underlying symbol e.g. NIFTY, BANKNIFTY, SENSEX"),
    segment: str = Query("option", description="Segment: option or future"),
    option_type: Optional[str] = Query("CE", description="CE or PE"),
    expiry: Optional[str] = Query(None, description="Target expiry date"),
    strike: Optional[float] = Query(None, description="Target strike price"),
    user_id: str = Depends(get_current_user),
):
    """
    Returns live spot price, calculated nearest ATM strike, available expiries (running, next, upcoming),
    available strikes list, and official lot size from Scrip Master.
    """
    sym = symbol.upper()
    seg = segment.lower()
    opt = (option_type or "CE").upper()

    # 1. Fetch live Spot LTP
    spot_info = scrip_master.get_spot_info(sym)
    spot_ltp = 0.0
    if spot_info:
        try:
            spot_ltp = angel_client.get_ltp(
                exchange=spot_info["exchange"],
                tradingsymbol=spot_info["tradingsymbol"],
                symboltoken=spot_info["symboltoken"],
            )
        except Exception as e:
            logger.warning(f"Could not fetch live spot for {sym}: {e}")

    # 2. Strike step & ATM strike calculation
    strike_step = scrip_master.get_strike_step(sym)
    atm_strike = scrip_master.calculate_atm_strike(sym, spot_ltp, opt) if spot_ltp > 0 else None

    # 3. Available Expiries from Scrip Master
    expiries = scrip_master.get_expiries(sym, seg)
    running_expiry = expiries[0]["expiry"] if expiries and isinstance(expiries[0], dict) else (expiries[0] if expiries else None)
    next_expiry = expiries[1]["expiry"] if len(expiries) > 1 and isinstance(expiries[1], dict) else (expiries[1] if len(expiries) > 1 else None)

    chosen_expiry = expiry if expiry else running_expiry

    # 4. Available Strikes for chosen expiry
    strikes = scrip_master.get_strikes(sym, chosen_expiry) if seg == "option" else []

    # 5. Lot Size
    lot_size = scrip_master.get_lot_size(sym)

    # 6. If target strike provided or ATM strike calculated, fetch contract LTP
    contract_ltp = None
    contract_tradingsymbol = None
    target_strike = strike
    if target_strike is not None and strikes and target_strike not in strikes:
        target_strike = atm_strike
    if target_strike is None:
        target_strike = atm_strike

    resolved_contract_info = None
    if seg == "option" and target_strike:
        contract = scrip_master.find_contract(
            symbol=sym,
            segment="option",
            expiry=chosen_expiry,
            strike=target_strike,
            option_type=opt,
        )
        if contract:
            contract_tradingsymbol = contract.get("tradingsymbol")
            resolved_contract_info = contract
            try:
                contract_ltp = angel_client.get_ltp(
                    exchange=contract["exchange"],
                    tradingsymbol=contract["tradingsymbol"],
                    symboltoken=contract["symboltoken"],
                )
            except Exception as e:
                logger.warning(f"Could not fetch option contract LTP: {e}")
    elif seg == "future":
        contract = scrip_master.find_contract(
            symbol=sym,
            segment="future",
            expiry=chosen_expiry,
        )
        if contract:
            contract_tradingsymbol = contract.get("tradingsymbol")
            resolved_contract_info = contract
            try:
                contract_ltp = angel_client.get_ltp(
                    exchange=contract["exchange"],
                    tradingsymbol=contract["tradingsymbol"],
                    symboltoken=contract["symboltoken"],
                )
            except Exception as e:
                logger.warning(f"Could not fetch future contract LTP: {e}")

    # For MCX commodities, there is no spot index; reference price is the nearest future's LTP
    if scrip_master.get_instrument_type(sym) == "MCX":
        spot_ltp = contract_ltp or 0.0

    return {
        "status": "success",
        "symbol": sym,
        "segment": seg,
        "instrument_type": scrip_master.get_instrument_type(sym),
        "spot_ltp": spot_ltp,
        "strike_step": strike_step,
        "atm_strike": atm_strike,
        "expiries": expiries,
        "running_expiry": running_expiry,
        "next_expiry": next_expiry,
        "selected_expiry": chosen_expiry,
        "strikes": strikes,
        "lot_size": lot_size,
        "contract_ltp": contract_ltp,
        "contract_tradingsymbol": contract_tradingsymbol,
        "resolved_contract": resolved_contract_info,
    }


@router.get("/ltp")
async def get_instrument_ltp(
    symbol: str = Query(..., description="Underlying or Stock symbol e.g. NIFTY, SENSEX, RELIANCE"),
    segment: Optional[str] = Query(None, description="Segment: cash, future, option"),
    expiry: Optional[str] = Query(None, description="Expiry date string e.g. 29SEP2026"),
    strike: Optional[float] = Query(None, description="Strike price e.g. 23400"),
    option_type: Optional[str] = Query(None, description="Option Type: CE or PE"),
    user_id: str = Depends(get_current_user),
):
    """Resolve instrument details and return real-time LTP from AngelOne."""
    sym = symbol.upper()
    inst_type = scrip_master.get_instrument_type(sym)
    if segment:
        seg = segment.lower()
        if inst_type == "MCX" and seg == "cash":
            seg = "future"
    else:
        seg = "future" if inst_type == "MCX" else "cash"

    # Step 1: Try resolving via Scrip Master
    inst = scrip_master.find_contract(
        symbol=sym,
        segment=seg,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
    )

    # Step 2: Fallback to MongoDB instruments collection if not in scrip master
    if not inst:
        inst = await angel_client.lookup_instrument(
            symbol=sym,
            segment=seg,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
        )

    if not inst:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument '{symbol}' (segment={segment}, strike={strike}, type={option_type}) not found",
        )

    try:
        price = angel_client.get_ltp(
            exchange=inst["exchange"],
            tradingsymbol=inst["tradingsymbol"],
            symboltoken=inst["symboltoken"],
        )
        return {
            "status": "success",
            "symbol": sym,
            "tradingsymbol": inst["tradingsymbol"],
            "exchange": inst["exchange"],
            "symboltoken": inst["symboltoken"],
            "ltp": price,
            "lot_size": inst.get("lot_size", 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except LTPFetchError as e:
        logger.error(f"LTP fetch failed for user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch live market price from broker: {str(e)}",
        )


# ---------------------------------------------------------------------------
# 3. Trade Execution Logic
# ---------------------------------------------------------------------------
async def _execute_trade(
    user_id: str,
    segment: str,
    instrument_symbol: str,
    action: str,
    qty: Optional[int] = None,
    lots: Optional[int] = 1,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Thin wrapper: permission check -> resolve -> fetch price -> open_position."""
    db = get_db()
    extra_fields = extra_fields or {}

    # Step 1: Verify Segment Permission directly from DB
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found")

    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    allowed_segments = user.get("allowed_segments", [])
    if segment not in allowed_segments:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Trading in segment '{segment}' is not permitted for your account.",
        )

    trade_limit = user.get("trade_limit")
    trades_used = user.get("trades_used", {})
    if trade_limit and segment in trade_limit:
        if trades_used.get(segment, 0) >= trade_limit[segment]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Trade limit exhausted for {segment}",
            )

    # Step 2: Resolve Contract
    contract = await resolve_contract(
        segment=segment,
        symbol=instrument_symbol,
        expiry=extra_fields.get("expiry"),
        strike=extra_fields.get("strike"),
        option_type=extra_fields.get("option_type"),
    )

    # Step 3: Verify Instrument Type Permission (INDEX vs MCX)
    sym = (contract.get("symbol") or instrument_symbol).upper()
    inst_type = contract.get("instrument_type") or scrip_master.get_instrument_type(sym)
    allowed_inst_types = user.get("allowed_instrument_types", ["INDEX"])
    if inst_type not in allowed_inst_types:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Trading in instrument type '{inst_type}' is not permitted for your account.",
        )

    # Step 4: Verify Market Hours
    exchange = contract.get("exchange", "NSE")
    from market_calendar import is_market_open
    if not is_market_open(exchange):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Market closed for {exchange}",
        )

    # Step 5: Fetch live LTP Quote
    try:
        price = angel_client.get_ltp(
            exchange=contract["exchange"],
            tradingsymbol=contract["tradingsymbol"],
            symboltoken=contract["symboltoken"],
        )
    except Exception as err:
        logger.warning(f"Live price unavailable for {contract.get('tradingsymbol')}: {err}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Live price unavailable, try again",
        )

    if not price or price <= 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Live price unavailable, try again",
        )

    # Step 6: Open Position
    trade = await open_position(
        user_id=user_id,
        segment=segment,
        contract=contract,
        action=action,
        lots=lots,
        qty=qty,
        price=price,
        source="MARKET",
        extra=extra_fields,
    )
    return trade


@router.post("/trade/option")
async def trade_option(
    data: TradeOptionCreate,
    user_id: str = Depends(get_current_user),
):
    """Place simulated Option order (auto-resolves ATM strike / scrip master chain)."""
    extra = {
        "expiry": data.expiry,
        "strike": data.strike,
        "option_type": data.option_type,
    }
    result = await _execute_trade(
        user_id=user_id,
        segment="option",
        instrument_symbol=data.instrument,
        action=data.action,
        qty=data.qty,
        lots=data.lots,
        extra_fields=extra,
    )
    return {"status": "success", "message": "Option trade executed", "trade": result}


@router.post("/trade/future")
async def trade_future(
    data: TradeFutureCreate,
    user_id: str = Depends(get_current_user),
):
    """Place simulated Futures order."""
    extra = {
        "expiry": data.expiry,
    }
    result = await _execute_trade(
        user_id=user_id,
        segment="future",
        instrument_symbol=data.instrument,
        action=data.action,
        qty=data.qty,
        lots=data.lots,
        extra_fields=extra,
    )
    return {"status": "success", "message": "Future trade executed", "trade": result}


@router.post("/trade/cash")
async def trade_cash(
    data: TradeCashCreate,
    user_id: str = Depends(get_current_user),
):
    """Place simulated Cash (Equity) order."""
    result = await _execute_trade(
        user_id=user_id,
        segment="cash",
        instrument_symbol=data.instrument,
        action=data.action,
        qty=data.qty,
        lots=1,
    )
    return {"status": "success", "message": "Cash trade executed", "trade": result}


# ---------------------------------------------------------------------------
# 4. Trade Square-Off / Close Single Trade
# ---------------------------------------------------------------------------
@router.post("/trade/{segment}/{trade_id}/close")
async def close_trade(
    segment: str,
    trade_id: str,
    user_id: str = Depends(get_current_user),
):
    """Close/square-off an active open trade, fetch live exit price, compute PnL, release margin & apply realized P&L."""
    segment = segment.lower()
    if segment not in ("option", "future", "cash"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid segment '{segment}'")

    db = get_db()
    coll_name = f"trades_{segment}"

    # Verify ownership and state
    trade = await db[coll_name].find_one({"trade_id": trade_id, "user_id": user_id})
    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trade '{trade_id}' not found or does not belong to your account",
        )

    if trade.get("status") != "OPEN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trade '{trade_id}' is already {trade.get('status')}",
        )

    # Fetch live exit price (real broker price required)
    try:
        exit_price = angel_client.get_ltp(
            exchange=trade.get("exchange", "NSE"),
            tradingsymbol=trade.get("tradingsymbol", trade.get("instrument")),
            symboltoken=trade.get("symboltoken", ""),
        )
    except Exception as err:
        logger.warning(f"Exit price fetch failed for {trade.get('tradingsymbol')}: {err}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Live price unavailable, try again",
        )

    if not exit_price or exit_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Live price unavailable, try again",
        )

    # Core PnL, margin release & DB update via shared _close_single_trade
    closed_trade = await _close_single_trade(
        segment=segment,
        trade=trade,
        exit_price=exit_price,
        closed_by=user_id,
    )

    if not closed_trade:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trade '{trade_id}' is already CLOSED",
        )

    return {
        "status": "success",
        "message": f"Trade {trade_id} squared off successfully",
        "trade": closed_trade,
    }


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 5. User Trade Book & Limit Status
# ---------------------------------------------------------------------------
@router.get("/trades")
async def get_user_trades(
    segment: Optional[str] = Query(None, description="option, future, or cash"),
    status_filter: Optional[str] = Query(None, description="OPEN or CLOSED"),
    user_id: str = Depends(get_current_user),
):
    """Retrieve user's execution history with live MTM for open positions."""
    db = get_db()
    segments = [segment.lower()] if segment else ["option", "future", "cash"]
    trades: List[Dict[str, Any]] = []

    for seg in segments:
        if seg not in ("option", "future", "cash"):
            continue
        coll = db[f"trades_{seg}"]
        query: Dict[str, Any] = {"user_id": user_id}
        if status_filter:
            query["status"] = status_filter.upper()

        cursor = coll.find(query, {"_id": 0}).sort("entry_time", pymongo.DESCENDING)
        seg_trades = await cursor.to_list(length=500)
        trades.extend(seg_trades)

    # Calculate real-time MTM for open trades
    total_unrealized_pnl = 0.0
    total_realized_pnl = 0.0

    for t in trades:
        entry = float(t.get("entry_price", 0.0))
        pnl_qty = float(t.get("pnl_qty", t.get("qty", 1)))
        action = t.get("action", "BUY").upper()
        multiplier = 1.0 if action == "BUY" else -1.0

        if t.get("status") == "OPEN":
            # Attempt to fetch live quote for active unrealized P&L
            try:
                cur_ltp = angel_client.get_ltp(
                    exchange=t.get("exchange", "NSE"),
                    tradingsymbol=t.get("tradingsymbol", t.get("instrument")),
                    symboltoken=t.get("symboltoken", ""),
                )
                pnl = round((cur_ltp - entry) * pnl_qty * multiplier, 2)
                t["current_ltp"] = cur_ltp
                t["current_price"] = cur_ltp
                t["pnl"] = pnl
                t["is_unrealized"] = True
                total_unrealized_pnl += pnl
            except Exception as e:
                logger.debug(f"Could not calculate live unrealized PnL for trade {t.get('trade_id')}: {e}")
                t["current_ltp"] = entry
                t["current_price"] = entry
                t["pnl"] = 0.0
                t["is_unrealized"] = True
        else:
            t["current_ltp"] = t.get("exit_price")
            t["current_price"] = t.get("exit_price")
            t["is_unrealized"] = False
            total_realized_pnl += float(t.get("pnl", 0.0))

    return {
        "status": "success",
        "segment": segment,
        "count": len(trades),
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_realized_pnl": round(total_realized_pnl, 2),
        "total_net_pnl": round(total_unrealized_pnl + total_realized_pnl, 2),
        "trades": trades,
    }


@router.get("/trades/{segment}")
async def get_user_trades_by_path(
    segment: str,
    status_filter: Optional[str] = Query(None, description="OPEN or CLOSED"),
    user_id: str = Depends(get_current_user),
):
    """Retrieve user's execution history by path segment parameter."""
    return await get_user_trades(segment=segment, status_filter=status_filter, user_id=user_id)



@router.get("/limit-status")
async def get_limit_status(user_id: str = Depends(get_current_user)):
    """Return account balance, available margin, blocked margin, equity, loss percentage, and risk level."""
    db = get_db()
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    allowed_segments: List[str] = user.get("allowed_segments", [])

    balance = float(user.get("balance", 0.0))
    available_balance = float(user.get("available_balance", 0.0))
    margin_blocked = float(user.get("margin_blocked", 0.0))
    realized_pnl = float(user.get("realized_pnl", 0.0))
    unrealized_pnl = float(user.get("unrealized_pnl", 0.0))
    equity = float(user.get("equity", balance + realized_pnl + unrealized_pnl))
    loss_pct = float(user.get("loss_pct", 0.0))
    auto_square_off_pct = float(user.get("auto_square_off_pct", 80.0))

    if loss_pct >= 80.0:
        risk_level = "critical"
    elif loss_pct >= 60.0:
        risk_level = "warning"
    else:
        risk_level = "normal"

    pending_cursor = db.orders.find({"user_id": user_id, "status": "PENDING"})
    pending_orders_list = await pending_cursor.to_list(length=500)
    pending_count = len(pending_orders_list)
    pending_reserved = round(sum(float(o.get("reserved_total", 0.0)) for o in pending_orders_list), 2)

    trade_limit = user.get("trade_limit") or {"option": 100, "future": 100, "cash": 100}
    trades_used = user.get("trades_used") or {"option": 0, "future": 0, "cash": 0}
    remaining_limit = {
        seg: max(0, trade_limit.get(seg, 100) - trades_used.get(seg, 0))
        for seg in ("option", "future", "cash")
    }

    return {
        "status": "success",
        "user_id": user_id,
        "name": user.get("name", ""),
        "allowed_segments": allowed_segments,
        "allowed_instrument_types": user.get("allowed_instrument_types", ["INDEX"]),
        "balance": balance,
        "available_balance": available_balance,
        "margin_blocked": margin_blocked,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "equity": equity,
        "loss_pct": loss_pct,
        "auto_square_off_pct": auto_square_off_pct,
        "risk_level": risk_level,
        "total_brokerage_paid": float(user.get("total_brokerage_paid", 0.0)),
        "pending_orders_count": pending_count,
        "pending_reserved": pending_reserved,
        "trade_limit": trade_limit,
        "trades_used": trades_used,
        "remaining_limit": remaining_limit,
    }


@router.get("/brokerage-preview", response_model=BrokeragePreviewOut)
async def get_brokerage_preview(
    segment: str = Query(..., description="Trade segment: option, future, or cash"),
    instrument: str = Query(..., description="Symbol e.g. NIFTY, GOLD, RELIANCE"),
    lots: int = Query(1, ge=1),
    qty: Optional[int] = Query(None, ge=1),
    price: Optional[float] = Query(None, ge=0),
    strike: Optional[float] = Query(None),
    option_type: Optional[str] = Query(None),
    expiry: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
):
    """Preview brokerage estimation for a trade order."""
    seg = segment.lower()
    sym = instrument.upper()

    contract = await resolve_contract(
        segment=seg,
        symbol=sym,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
    )

    trade_price = price
    if trade_price is None or trade_price <= 0:
        try:
            trade_price = angel_client.get_ltp(
                exchange=contract.get("exchange", "NSE"),
                tradingsymbol=contract["tradingsymbol"],
                symboltoken=str(contract["symboltoken"]),
            )
        except Exception:
            trade_price = 0.0

    lot_size = contract.get("lot_size", 1)
    final_lots = lots or 1
    final_qty = qty if qty and qty > 0 else final_lots * lot_size
    num_lots = final_lots if final_lots > 0 else max(1, final_qty // lot_size if lot_size > 0 else 1)

    inst_type = contract.get("instrument_type") or scrip_master.get_instrument_type(sym)
    pnl_mult = contract.get("pnl_multiplier_per_lot")
    if pnl_mult is None:
        pnl_mult = scrip_master.get_pnl_multiplier(sym, lot_size=lot_size)
    if pnl_mult is None:
        pnl_mult = float(lot_size)
    else:
        pnl_mult = float(pnl_mult)

    pnl_qty = round(num_lots * pnl_mult, 4)

    cfg = await resolve_brokerage_config(
        user_id=user_id,
        segment=seg,
        instrument_type=inst_type,
    )

    estimated_brokerage = compute_brokerage(
        config=cfg,
        price=trade_price,
        lots=num_lots,
        pnl_qty=pnl_qty,
    )

    contract_value = round(trade_price * pnl_qty, 2) if inst_type == "MCX" else round(trade_price * final_qty, 2)
    rate = float(cfg.get("value", 0.0)) if cfg else 0.0
    mode = cfg.get("mode", "PER_LOT") if cfg else "NONE"

    return BrokeragePreviewOut(
        segment=seg,
        instrument=sym,
        instrument_type=inst_type,
        mode=mode,
        rate=rate,
        estimated_brokerage=estimated_brokerage,
        contract_value=contract_value,
    )


# ---------------------------------------------------------------------------
# 10. Pending (Limit) Orders
# ---------------------------------------------------------------------------
@router.post("/order/{segment}")
async def place_limit_order(
    segment: str,
    body: OrderCreate,
    user_id: str = Depends(get_current_user),
):
    """Place a limit order. If market is open and price is marketable, execute immediately via open_position.
    Otherwise atomically reserve R = lock + brokerage and store as PENDING.
    """
    db = get_db()
    seg = segment.lower()
    if seg not in ("option", "future", "cash"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid segment '{segment}'")

    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    allowed_segments = user.get("allowed_segments", [])
    if seg not in allowed_segments:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Segment '{seg}' is not allowed for your account",
        )

    # Resolve contract
    contract = await resolve_contract(
        segment=seg,
        symbol=body.instrument,
        expiry=body.expiry,
        strike=body.strike,
        option_type=body.option_type,
    )

    sym = (contract.get("symbol") or body.instrument).upper()
    inst_type = contract.get("instrument_type") or scrip_master.get_instrument_type(sym)
    allowed_inst_types = user.get("allowed_instrument_types", ["INDEX"])
    if inst_type not in allowed_inst_types:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Instrument type '{inst_type}' not permitted for your account",
        )

    exch = contract.get("exchange", "NSE")
    current_time_ist = market_calendar.now_ist()

    # Check contract expiry
    exp_str = contract.get("expiry")
    if exp_str and market_calendar.contract_expired(exch, exp_str, current_time=current_time_ist):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Contract '{contract.get('tradingsymbol')}' has expired",
        )

    # Tick size check & rounding
    tick_size = float(contract.get("tick_size") or 0.05)
    limit_price = round(round(body.limit_price / tick_size) * tick_size, 2)

    lot_size = contract.get("lot_size", 1)
    final_lots = body.lots or 1
    final_qty = body.qty if body.qty and body.qty > 0 else final_lots * lot_size
    num_lots = final_lots if final_lots > 0 else max(1, final_qty // lot_size if lot_size > 0 else 1)

    pnl_mult = contract.get("pnl_multiplier_per_lot")
    if pnl_mult is None:
        pnl_mult = scrip_master.get_pnl_multiplier(sym, lot_size=lot_size)
    if pnl_mult is None:
        pnl_mult = float(lot_size)
    else:
        pnl_mult = float(pnl_mult)
    pnl_qty = round(num_lots * pnl_mult, 4)

    now_utc = datetime.now(timezone.utc)
    order_id = f"ORD-{seg.upper()[:3]}-{uuid.uuid4().hex[:8].upper()}"

    # Market open & marketable check
    market_open = market_calendar.is_market_open(exch, current_time_ist)
    is_marketable = False
    live_price = None

    if market_open:
        try:
            live_price = angel_client.get_ltp(
                exchange=exch,
                tradingsymbol=contract["tradingsymbol"],
                symboltoken=str(contract["symboltoken"]),
            )
            if live_price and live_price > 0:
                if body.action.upper() == "BUY" and limit_price >= live_price:
                    is_marketable = True
                elif body.action.upper() == "SELL" and limit_price <= live_price:
                    is_marketable = True
        except Exception as e:
            logger.debug(f"Could not fetch live LTP for marketable check: {e}")

    # If market is OPEN and order is marketable -> fill immediately via open_position
    if is_marketable and live_price:
        trade = await open_position(
            user_id=user_id,
            segment=seg,
            contract=contract,
            action=body.action,
            lots=num_lots,
            qty=final_qty,
            price=live_price,
            source="LIMIT_ORDER",
            extra={
                "order_id": order_id,
                "strike": body.strike,
                "option_type": body.option_type,
                "expiry": body.expiry,
                "product": body.product or "CF",
            },
        )
        order_doc = {
            "order_id": order_id,
            "user_id": user_id,
            "segment": seg,
            "instrument_type": inst_type,
            "instrument": sym,
            "tradingsymbol": contract["tradingsymbol"],
            "exchange": exch,
            "symboltoken": str(contract["symboltoken"]),
            "expiry": contract.get("expiry"),
            "strike": contract.get("strike"),
            "option_type": contract.get("option_type"),
            "lot_size": lot_size,
            "lots": num_lots,
            "qty": final_qty,
            "pnl_qty": pnl_qty,
            "pnl_multiplier_per_lot": pnl_mult,
            "action": body.action.upper(),
            "order_type": "LIMIT",
            "limit_price": limit_price,
            "status": "EXECUTED",
            "reserved_total": 0.0,
            "reserved_lock": 0.0,
            "reserved_brokerage": 0.0,
            "version": 1,
            "created_at": now_utc,
            "modified_at": now_utc,
            "executed_at": now_utc,
            "executed_price": live_price,
            "trade_id": trade["trade_id"],
            "reject_reason": None,
            "cancelled_by": None,
            "history": [{"action": "MARKETABLE_IMMEDIATE_FILL", "fill_price": live_price, "timestamp": now_utc}],
            "product": "CF" if seg == "option" else (body.product or "NRML"),
        }
        await db.orders.insert_one(order_doc)
        order_doc.pop("_id", None)
        return {
            "status": "success",
            "message": "Marketable limit order executed immediately at market price",
            "order": order_doc,
            "trade": trade,
        }

    # Otherwise order stays PENDING -> Atomically reserve R = lock + brokerage computed at limit_price
    r_lock = await compute_required_lock(seg, contract, limit_price, num_lots, final_qty)
    brok_cfg = await resolve_brokerage_config(user_id, seg, inst_type)
    r_brok = compute_brokerage(brok_cfg, limit_price, num_lots, pnl_qty)
    r_total = round(r_lock + r_brok, 2)

    # Balance guard
    user_res = await db.users.find_one_and_update(
        {
            "user_id": user_id,
            "$expr": {"$gte": ["$available_balance", r_total]},
        },
        {
            "$inc": {
                "available_balance": -r_total,
                "margin_blocked": r_total,
            },
            "$set": {"updated_at": now_utc},
        },
        return_document=ReturnDocument.AFTER,
    )

    if not user_res:
        user_fresh = await db.users.find_one({"user_id": user_id})
        available = float(user_fresh.get("available_balance", 0.0)) if user_fresh else 0.0
        shortfall = round(max(0.0, r_total - available), 2)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Insufficient margin. Required: ₹{r_total:,.2f} "
                f"(Margin: ₹{r_lock:,.2f}, Brokerage: ₹{r_brok:,.2f}, Total: ₹{r_total:,.2f}), "
                f"Available: ₹{available:,.2f}, Shortfall: ₹{shortfall:,.2f}"
            ),
        )

    order_doc = {
        "order_id": order_id,
        "user_id": user_id,
        "segment": seg,
        "instrument_type": inst_type,
        "instrument": sym,
        "tradingsymbol": contract["tradingsymbol"],
        "exchange": exch,
        "symboltoken": str(contract["symboltoken"]),
        "expiry": contract.get("expiry"),
        "strike": contract.get("strike"),
        "option_type": contract.get("option_type"),
        "lot_size": lot_size,
        "lots": num_lots,
        "qty": final_qty,
        "pnl_qty": pnl_qty,
        "pnl_multiplier_per_lot": pnl_mult,
        "action": body.action.upper(),
        "order_type": "LIMIT",
        "limit_price": limit_price,
        "status": "PENDING",
        "reserved_total": r_total,
        "reserved_lock": r_lock,
        "reserved_brokerage": r_brok,
        "version": 1,
        "created_at": now_utc,
        "modified_at": now_utc,
        "executed_at": None,
        "executed_price": None,
        "trade_id": None,
        "reject_reason": None,
        "cancelled_by": None,
        "history": [{"action": "CREATE", "timestamp": now_utc}],
        "product": "CF" if seg == "option" else (body.product or "NRML"),
    }
    await db.orders.insert_one(order_doc)
    order_doc.pop("_id", None)
    return {
        "status": "success",
        "message": "Limit order placed successfully and is now pending",
        "order": order_doc,
    }


@router.put("/order/{order_id}")
async def modify_pending_order(
    order_id: str,
    body: OrderModify,
    user_id: str = Depends(get_current_user),
):
    """Modify limit_price and/or lots of a PENDING order with mutex claim and delta reserve adjustment."""
    db = get_db()
    now_utc = datetime.now(timezone.utc)

    # 1. Mutex Claim: PENDING -> MODIFYING
    claimed = await db.orders.find_one_and_update(
        {"order_id": order_id, "user_id": user_id, "status": "PENDING"},
        {"$set": {"status": "MODIFYING", "modified_at": now_utc}},
        return_document=ReturnDocument.AFTER,
    )
    if not claimed:
        existing = await db.orders.find_one({"order_id": order_id, "user_id": user_id})
        current_status = existing.get("status") if existing else "NOT_FOUND"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if current_status in ("EXECUTED", "CANCELLED") else status.HTTP_400_BAD_REQUEST,
            detail=f"Order cannot be modified (current status: {current_status})",
        )

    # 2. Compute new required reserve R'
    seg = claimed["segment"]
    lot_size = claimed["lot_size"]
    new_price = body.limit_price if body.limit_price is not None else claimed["limit_price"]
    new_lots = body.lots if body.lots is not None else claimed["lots"]
    new_qty = body.qty if body.qty is not None else (new_lots * lot_size)
    pnl_mult = float(claimed.get("pnl_multiplier_per_lot") or lot_size)
    new_pnl_qty = round(new_lots * pnl_mult, 4)

    contract = {
        "symbol": claimed["instrument"],
        "tradingsymbol": claimed["tradingsymbol"],
        "exchange": claimed.get("exchange", "NSE"),
        "symboltoken": claimed["symboltoken"],
        "lot_size": lot_size,
        "pnl_multiplier_per_lot": pnl_mult,
        "instrument_type": claimed["instrument_type"],
    }

    new_lock = await compute_required_lock(seg, contract, new_price, new_lots, new_qty)
    brok_cfg = await resolve_brokerage_config(user_id, seg, claimed["instrument_type"])
    new_brok = compute_brokerage(brok_cfg, new_price, new_lots, new_pnl_qty)
    r_prime = round(new_lock + new_brok, 2)

    r_old = float(claimed.get("reserved_total", 0.0))
    delta = round(r_prime - r_old, 2)

    # 3. Apply delta with guard if delta > 0
    if delta > 0:
        user_update = await db.users.find_one_and_update(
            {
                "user_id": user_id,
                "$expr": {"$gte": ["$available_balance", delta]},
            },
            {
                "$inc": {
                    "available_balance": -delta,
                    "margin_blocked": delta,
                },
                "$set": {"updated_at": now_utc},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not user_update:
            # Insufficient balance: Revert order back to PENDING with old values
            await db.orders.update_one(
                {"order_id": order_id},
                {
                    "$set": {"status": "PENDING", "modified_at": now_utc},
                    "$push": {
                        "history": {
                            "action": "MODIFY_FAILED_INSUFFICIENT_FUNDS",
                            "delta_required": delta,
                            "timestamp": now_utc,
                        }
                    },
                },
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient balance to increase order size/price. Additional required: ₹{delta:,.2f}",
            )
    elif delta < 0:
        # Credit back excess reservation
        credit = abs(delta)
        await db.users.update_one(
            {"user_id": user_id},
            {
                "$inc": {
                    "available_balance": credit,
                    "margin_blocked": -credit,
                },
                "$set": {"updated_at": now_utc},
            },
        )

    # 4. Successfully update order and restore PENDING status with incremented version
    updated_order = await db.orders.find_one_and_update(
        {"order_id": order_id},
        {
            "$set": {
                "limit_price": new_price,
                "lots": new_lots,
                "qty": new_qty,
                "pnl_qty": new_pnl_qty,
                "reserved_total": r_prime,
                "reserved_lock": new_lock,
                "reserved_brokerage": new_brok,
                "status": "PENDING",
                "modified_at": now_utc,
            },
            "$inc": {"version": 1},
            "$push": {
                "history": {
                    "action": "MODIFY",
                    "old_price": claimed["limit_price"],
                    "new_price": new_price,
                    "old_lots": claimed["lots"],
                    "new_lots": new_lots,
                    "delta_reserved": delta,
                    "timestamp": now_utc,
                }
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated_order:
        updated_order.pop("_id", None)
    return {
        "status": "success",
        "message": "Order modified successfully",
        "order": updated_order,
    }


@router.delete("/order/{order_id}")
async def cancel_pending_order(
    order_id: str,
    user_id: str = Depends(get_current_user),
):
    """Atomically cancel a PENDING order and refund reserved margin & brokerage."""
    db = get_db()
    now_utc = datetime.now(timezone.utc)

    # Atomic cancellation claim
    claimed = await db.orders.find_one_and_update(
        {"order_id": order_id, "user_id": user_id, "status": "PENDING"},
        {
            "$set": {
                "status": "CANCELLED",
                "cancelled_by": user_id,
                "modified_at": now_utc,
            },
            "$inc": {"version": 1},
            "$push": {"history": {"action": "CANCEL", "by": user_id, "timestamp": now_utc}},
        },
        return_document=ReturnDocument.AFTER,
    )

    if not claimed:
        existing = await db.orders.find_one({"order_id": order_id, "user_id": user_id})
        current_status = existing.get("status") if existing else "NOT_FOUND"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if current_status in ("EXECUTED", "CANCELLED") else status.HTTP_400_BAD_REQUEST,
            detail=f"Order cannot be cancelled (current status: {current_status})",
        )

    # Release reserved total back to user
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

    claimed.pop("_id", None)
    return {
        "status": "success",
        "message": f"Order {order_id} cancelled successfully, refunded ₹{reserved:,.2f}",
        "order": claimed,
    }


@router.get("/orders")
async def get_user_orders(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (PENDING, EXECUTED, CANCELLED, REJECTED)"),
    user_id: str = Depends(get_current_user),
):
    """List orders for the authenticated user, optionally filtered by status."""
    db = get_db()
    q: Dict[str, Any] = {"user_id": user_id}
    if status_filter:
        q["status"] = status_filter.upper()

    cursor = db.orders.find(q, {"_id": 0}).sort("created_at", pymongo.DESCENDING)
    orders = await cursor.to_list(length=500)
    return {
        "status": "success",
        "count": len(orders),
        "orders": orders,
    }


