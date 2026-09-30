"""Order Engine Service
Handles pending limit orders, background evaluation loop, fill execution, mutex modify recovery,
and cancellation cascades.

Known limit: Polling every 3-5 seconds can miss a price touch between cycles.
A websocket feed is planned as a future upgrade.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from pymongo import ReturnDocument

from db import get_db
from angelone_client import angel_client
import market_calendar
from scrip_master import scrip_master
from trade_engine import compute_required_lock, resolve_brokerage_config, compute_brokerage

logger = logging.getLogger("virtual_trading_platform.order_engine")


async def cancel_all_user_pending_orders(
    user_id: str,
    cancelled_by: str = "SYSTEM_AUTO_SQUARE_OFF",
) -> int:
    """Atomically cancels all PENDING and MODIFYING orders for a user and refunds reserved funds.
    Used before auto square-off, admin force-close, or account deactivation.
    """
    db = get_db()
    cursor = db.orders.find({"user_id": user_id, "status": {"$in": ["PENDING", "MODIFYING"]}})
    cancelled_count = 0
    now = datetime.now(timezone.utc)

    async for order in cursor:
        order_id = order["order_id"]
        # Atomic cancellation claim
        claimed = await db.orders.find_one_and_update(
            {"order_id": order_id, "status": {"$in": ["PENDING", "MODIFYING"]}},
            {
                "$set": {
                    "status": "CANCELLED",
                    "cancelled_by": cancelled_by,
                    "modified_at": now,
                },
                "$inc": {"version": 1},
                "$push": {
                    "history": {
                        "action": "CANCEL",
                        "cancelled_by": cancelled_by,
                        "timestamp": now,
                    }
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if claimed:
            reserved = float(claimed.get("reserved_total", 0.0))
            if reserved > 0:
                await db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {
                            "available_balance": reserved,
                            "margin_blocked": -reserved,
                        },
                        "$set": {"updated_at": now},
                    },
                )
            cancelled_count += 1
            logger.info(f"[OrderEngine] Cancelled pending order {order_id} for user {user_id}, released ₹{reserved}")

    return cancelled_count


async def run_order_cycle() -> None:
    """Single evaluation cycle of pending limit orders."""
    db = get_db()
    now_utc = datetime.now(timezone.utc)
    current_ist = market_calendar.now_ist()

    # 1. Sweep: Return any MODIFYING orders older than 30s back to PENDING
    stale_modify_threshold = now_utc - timedelta(seconds=30)
    stale_modifying_cursor = db.orders.find({
        "status": "MODIFYING",
        "modified_at": {"$lt": stale_modify_threshold},
    })
    async for st in stale_modifying_cursor:
        order_id = st["order_id"]
        reverted = await db.orders.find_one_and_update(
            {"order_id": order_id, "status": "MODIFYING"},
            {
                "$set": {"status": "PENDING", "modified_at": now_utc},
                "$inc": {"version": 1},
                "$push": {
                    "history": {
                        "action": "MUTEX_TIMEOUT_REVERT",
                        "timestamp": now_utc,
                        "detail": "Reverted from MODIFYING to PENDING after 30s timeout",
                    }
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if reverted:
            logger.warning(f"[OrderEngine] Reverted stuck MODIFYING order {order_id} back to PENDING.")

    # 2. Recovery check: EXECUTED orders with no trade_id older than 30s
    stale_exec_threshold = now_utc - timedelta(seconds=30)
    stale_executed = await db.orders.count_documents({
        "status": "EXECUTED",
        "trade_id": None,
        "executed_at": {"$lt": stale_exec_threshold},
    })
    if stale_executed > 0:
        logger.warning(f"[OrderEngine] Found {stale_executed} EXECUTED orders missing trade_id older than 30s!")

    # 3. Find all PENDING orders
    pending_orders = await db.orders.find({"status": "PENDING"}).to_list(length=1000)
    if not pending_orders:
        return

    # 4. Group by exchange and filter out closed sessions
    eligible_orders: List[Dict[str, Any]] = []
    unique_tokens: Dict[str, Dict[str, Any]] = {}

    for o in pending_orders:
        exch = o.get("exchange", "NSE")
        if not market_calendar.is_market_open(exch, current_ist):
            continue  # Market closed, order stays PENDING

        eligible_orders.append(o)
        key = f"{exch}:{o['symboltoken']}"
        if key not in unique_tokens:
            unique_tokens[key] = {
                "exchange": exch,
                "tradingsymbol": o["tradingsymbol"],
                "symboltoken": o["symboltoken"],
            }

    if not eligible_orders:
        return

    # 5. Fetch fresh live prices (only source="live" and fetched_at <= 10s)
    fresh_prices: Dict[str, float] = {}
    for key, info in unique_tokens.items():
        try:
            meta = angel_client.get_ltp_with_meta(
                exchange=info["exchange"],
                tradingsymbol=info["tradingsymbol"],
                symboltoken=info["symboltoken"],
            )
            # Require live price and freshness within 10 seconds
            if meta.get("source") == "live" and meta.get("fetched_at"):
                age = (datetime.now(timezone.utc) - meta["fetched_at"]).total_seconds()
                if age <= 10.0 and meta.get("price", 0) > 0:
                    fresh_prices[key] = float(meta["price"])
                else:
                    logger.debug(f"[OrderEngine] Price for {key} is {age:.1f}s old (>10s), skipping.")
        except Exception as e:
            logger.debug(f"[OrderEngine] LTP fetch failed for {key}: {e}")

    # 6. Evaluate triggers for each eligible order
    for order in eligible_orders:
        key = f"{order.get('exchange', 'NSE')}:{order['symboltoken']}"
        ltp = fresh_prices.get(key)
        if not ltp or ltp <= 0:
            continue

        limit_price = float(order.get("limit_price") or order.get("price") or 0.0)
        action = (order.get("action") or "").upper()

        is_triggered = False
        if action == "BUY" and ltp <= limit_price:
            is_triggered = True
        elif action == "SELL" and ltp >= limit_price:
            is_triggered = True

        if not is_triggered:
            continue

        fill_price = ltp
        order_id = order["order_id"]
        user_id = order["user_id"]
        v = order.get("version", 1)

        # Atomic claim: PENDING -> EXECUTED
        claimed_order = await db.orders.find_one_and_update(
            {"order_id": order_id, "status": "PENDING", "version": v},
            {
                "$set": {
                    "status": "EXECUTED",
                    "executed_at": now_utc,
                    "executed_price": fill_price,
                    "modified_at": now_utc,
                },
                "$inc": {"version": 1},
                "$push": {
                    "history": {
                        "action": "EXECUTE_TRIGGERED",
                        "fill_price": fill_price,
                        "timestamp": now_utc,
                    }
                },
            },
            return_document=ReturnDocument.AFTER,
        )

        if not claimed_order:
            # Won by cancel or modify race condition
            continue

        # Compute fill requirements at fill_price
        seg = order["segment"]
        lots = order.get("lots", 1)
        qty = order.get("qty", 1)
        pnl_qty = order.get("pnl_qty", qty)
        inst_type = order.get("instrument_type", "INDEX")
        contract = {
            "symbol": order["instrument"],
            "tradingsymbol": order["tradingsymbol"],
            "exchange": order.get("exchange", "NSE"),
            "symboltoken": order["symboltoken"],
            "lot_size": order.get("lot_size", 1),
            "pnl_multiplier_per_lot": order.get("pnl_multiplier_per_lot"),
            "instrument_type": inst_type,
        }

        f_lock = await compute_required_lock(seg, contract, fill_price, lots, qty)
        brok_cfg = await resolve_brokerage_config(user_id, seg, inst_type)
        f_brok = compute_brokerage(brok_cfg, fill_price, lots, pnl_qty)

        reserved_total = float(order.get("reserved_total", 0.0))

        # Apply delta from reserved state to user balance
        # Formula:
        # available += R - F_lock - F_brok
        # margin_blocked += F_lock - R
        # realized_pnl -= F_brok
        # total_brokerage_paid += F_brok
        # Guard: available >= F_lock + F_brok - R
        delta_needed = round(f_lock + f_brok - reserved_total, 2)

        # Check guard on user
        guard_condition = (
            {"$expr": {"$gte": ["$available_balance", delta_needed]}}
            if delta_needed > 0
            else {}
        )
        user_query = {"user_id": user_id}
        if guard_condition:
            user_query.update(guard_condition)

        user_update = await db.users.find_one_and_update(
            user_query,
            {
                "$inc": {
                    "available_balance": -delta_needed,
                    "margin_blocked": round(f_lock - reserved_total, 2),
                    "realized_pnl": -f_brok,
                    "total_brokerage_paid": f_brok,
                    f"trades_used.{seg}": 1,
                },
                "$set": {"updated_at": now_utc},
            },
            return_document=ReturnDocument.AFTER,
        )

        if not user_update:
            # Insufficient balance at execution time: REJECT order & release full reserved R
            logger.warning(f"[OrderEngine] Order {order_id} failed balance guard at fill time. Rejecting.")
            await db.orders.update_one(
                {"order_id": order_id},
                {
                    "$set": {
                        "status": "REJECTED",
                        "reject_reason": f"Insufficient funds at execution: required additional ₹{delta_needed:,.2f}",
                        "modified_at": now_utc,
                    },
                    "$push": {
                        "history": {
                            "action": "REJECT_INSUFFICIENT_FUNDS",
                            "delta_needed": delta_needed,
                            "timestamp": now_utc,
                        }
                    },
                },
            )
            # Release full reserved amount
            if reserved_total > 0:
                await db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {
                            "available_balance": reserved_total,
                            "margin_blocked": -reserved_total,
                        },
                        "$set": {"updated_at": now_utc},
                    },
                )
            continue

        # Balance successfully transitioned. Create Trade record.
        trade_id = f"TRD-{seg.upper()[:3]}-{uuid.uuid4().hex[:8].upper()}"
        trade_doc: Dict[str, Any] = {
            "trade_id": trade_id,
            "order_id": order_id,
            "user_id": user_id,
            "segment": seg,
            "instrument": order["instrument"],
            "tradingsymbol": order["tradingsymbol"],
            "exchange": order.get("exchange", "NSE"),
            "symboltoken": str(order["symboltoken"]),
            "action": action,
            "qty": qty,
            "lot_size": order.get("lot_size", 1),
            "lots": lots,
            "instrument_type": inst_type,
            "pnl_multiplier_per_lot": order.get("pnl_multiplier_per_lot", 1.0),
            "pnl_qty": pnl_qty,
            "contract_value": round(fill_price * pnl_qty, 2) if inst_type == "MCX" else round(fill_price * qty, 2),
            "quote_unit": order.get("quote_unit", "₹/unit"),
            "entry_price": fill_price,
            "entry_time": now_utc,
            "exit_price": None,
            "exit_time": None,
            "status": "OPEN",
            "pnl": 0.0,
            "entry_brokerage": f_brok,
            "exit_brokerage": 0.0,
            "brokerage_mode": brok_cfg.get("mode") if brok_cfg else None,
            "brokerage_value": float(brok_cfg.get("value", 0.0)) if brok_cfg else 0.0,
            "brokerage_total": f_brok,
            "net_pnl": -f_brok,
            "margin_blocked_amount": f_lock,
            "product": "CF" if seg == "option" else order.get("product", "NRML"),
            "source": "LIMIT_ORDER",
            "created_at": now_utc,
            "updated_at": now_utc,
        }
        if order.get("strike") is not None:
            trade_doc["strike"] = order["strike"]
        if order.get("option_type") is not None:
            trade_doc["option_type"] = order["option_type"]
        if order.get("expiry") is not None:
            trade_doc["expiry"] = order["expiry"]

        await db[f"trades_{seg}"].insert_one(trade_doc)

        # Update order with trade_id
        await db.orders.update_one(
            {"order_id": order_id},
            {"$set": {"trade_id": trade_id, "modified_at": now_utc}},
        )
        logger.info(f"[OrderEngine] Order {order_id} EXECUTED at ₹{fill_price}, created trade {trade_id}")


async def start_order_engine(interval_seconds: float = 3.0):
    """Continuous background loop running order evaluation cycle."""
    logger.info("Order Engine started (Limit order evaluation loop, 3s cycle).")
    while True:
        try:
            await run_order_cycle()
        except asyncio.CancelledError:
            logger.info("Order Engine cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in Order Engine cycle: {e}", exc_info=True)

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Order Engine sleep cancelled.")
            break
