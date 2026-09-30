"""Settlement Engine Service
Handles automatic expiry settlement for expired option and future contracts:
1. Index Options: Evaluates intrinsic value against real underlying spot price:
   - CE = max(spot - strike, 0)
   - PE = max(strike - spot, 0)
   - Exit price = intrinsic (OTM expires at 0.0)
2. Index Futures: Exits at underlying's real closing price.
3. MCX Futures: Exits at last real traded price of that contract.
4. Cancels all pending orders on expired contracts and refunds reserved funds.
5. Emits detailed immutable audit logs for all settlements.
6. Retries next cycle if real market price is unavailable (never guesses).
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pymongo import ReturnDocument

from db import get_db
from angelone_client import angel_client
import market_calendar
from scrip_master import scrip_master, INDEX_CONFIGS
from mtm_engine import _close_single_trade

logger = logging.getLogger("virtual_trading_platform.settlement_engine")


async def run_settlement_cycle() -> Dict[str, Any]:
    """Single execution of contract expiry settlement.
    Idempotent and safe to run continuously and on server startup.
    """
    db = get_db()
    now_utc = datetime.now(timezone.utc)
    current_ist = market_calendar.now_ist()

    settled_trades: List[str] = []
    cancelled_orders: List[str] = []
    retry_trades: List[str] = []

    # 1. Cancel all PENDING / MODIFYING orders on expired contracts
    pending_cursor = db.orders.find({"status": {"$in": ["PENDING", "MODIFYING"]}})
    async for order in pending_cursor:
        exch = order.get("exchange", "NSE")
        exp_str = order.get("expiry")
        if not exp_str:
            continue

        if market_calendar.contract_expired(exch, exp_str, current_time=current_ist):
            order_id = order["order_id"]
            user_id = order["user_id"]
            claimed = await db.orders.find_one_and_update(
                {"order_id": order_id, "status": {"$in": ["PENDING", "MODIFYING"]}},
                {
                    "$set": {
                        "status": "CANCELLED",
                        "cancelled_by": "EXPIRY_SETTLEMENT",
                        "modified_at": now_utc,
                    },
                    "$inc": {"version": 1},
                    "$push": {
                        "history": {
                            "action": "EXPIRY_CANCEL",
                            "timestamp": now_utc,
                            "detail": f"Contract expired on {exp_str}",
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
                            "$set": {"updated_at": now_utc},
                        },
                    )
                cancelled_orders.append(order_id)
                logger.info(f"[Settlement] Cancelled expired order {order_id} for user {user_id}, released ₹{reserved}")

    # 2. Process all OPEN trades in options and futures
    for seg in ("option", "future"):
        open_trades = await db[f"trades_{seg}"].find({"status": "OPEN"}).to_list(length=1000)
        for trade in open_trades:
            exch = trade.get("exchange", "NSE")
            exp_str = trade.get("expiry")
            if not exp_str:
                continue

            if not market_calendar.contract_expired(exch, exp_str, current_time=current_ist):
                continue  # Contract not expired yet

            trade_id = trade["trade_id"]
            user_id = trade["user_id"]
            sym = (trade.get("instrument") or trade.get("symbol") or "").upper()
            if sym not in INDEX_CONFIGS:
                for k in INDEX_CONFIGS:
                    if sym.startswith(k):
                        sym = k
                        break
            inst_type = trade.get("instrument_type") or scrip_master.get_instrument_type(sym)

            exit_price: Optional[float] = None
            underlying_price: Optional[float] = None

            # A. Option Settlement
            if seg == "option":
                # Find spot contract
                spot_price = None
                if sym in INDEX_CONFIGS:
                    spot_info = INDEX_CONFIGS[sym]["spot"]
                    try:
                        spot_price = angel_client.get_ltp(
                            exchange=spot_info["exchange"],
                            tradingsymbol=spot_info["tradingsymbol"],
                            symboltoken=str(spot_info["token"]),
                        )
                    except Exception as e:
                        logger.warning(f"[Settlement] Failed to fetch spot price for {sym}: {e}")

                if spot_price is None or spot_price <= 0:
                    logger.warning(f"[Settlement] No spot price for trade {trade_id} ({sym}). Keeping OPEN and retrying.")
                    await db[f"trades_{seg}"].update_one(
                        {"trade_id": trade_id},
                        {"$set": {"needs_settlement": True, "updated_at": now_utc}},
                    )
                    retry_trades.append(trade_id)
                    continue

                underlying_price = float(spot_price)
                strike = float(trade.get("strike", 0.0))
                opt_type = (trade.get("option_type") or "CE").upper()

                if opt_type == "CE":
                    exit_price = max(0.0, round(underlying_price - strike, 2))
                else:  # PE
                    exit_price = max(0.0, round(strike - underlying_price, 2))

            # B. Future Settlement
            elif seg == "future":
                if inst_type == "MCX":
                    # MCX Futures: Last real traded price of that contract
                    try:
                        ltp = angel_client.get_ltp(
                            exchange=trade.get("exchange", "MCX"),
                            tradingsymbol=trade["tradingsymbol"],
                            symboltoken=str(trade["symboltoken"]),
                        )
                        if ltp and ltp > 0:
                            exit_price = float(ltp)
                            underlying_price = float(ltp)
                    except Exception as e:
                        logger.warning(f"[Settlement] Failed to fetch MCX contract price for {trade_id}: {e}")
                else:
                    # Index Futures: Underlying closing price
                    if sym in INDEX_CONFIGS:
                        spot_info = INDEX_CONFIGS[sym]["spot"]
                        try:
                            spot_price = angel_client.get_ltp(
                                exchange=spot_info["exchange"],
                                tradingsymbol=spot_info["tradingsymbol"],
                                symboltoken=str(spot_info["token"]),
                            )
                            if spot_price and spot_price > 0:
                                exit_price = float(spot_price)
                                underlying_price = float(spot_price)
                        except Exception as e:
                            logger.warning(f"[Settlement] Failed to fetch index spot price for future {trade_id}: {e}")

                if exit_price is None or exit_price <= 0:
                    logger.warning(f"[Settlement] No real price available for future trade {trade_id}. Retrying next cycle.")
                    await db[f"trades_{seg}"].update_one(
                        {"trade_id": trade_id},
                        {"$set": {"needs_settlement": True, "updated_at": now_utc}},
                    )
                    retry_trades.append(trade_id)
                    continue

            # Execute settlement close through _close_single_trade
            trade_to_close = dict(trade)
            trade_to_close["settlement_price"] = exit_price
            trade_to_close["underlying_price"] = underlying_price

            closed_trade = await _close_single_trade(
                segment=seg,
                trade=trade_to_close,
                exit_price=exit_price,
                closed_by="EXPIRY_SETTLEMENT",
            )

            if closed_trade:
                # Audit log entry
                audit_entry = {
                    "log_id": f"AUD-SETTL-{uuid.uuid4().hex[:8].upper()}",
                    "admin_id": "SYSTEM",
                    "actor": "SETTLEMENT_ENGINE",
                    "action": "EXPIRY_SETTLEMENT",
                    "target_user_id": user_id,
                    "details": {
                        "trade_id": trade_id,
                        "segment": seg,
                        "instrument": sym,
                        "tradingsymbol": trade.get("tradingsymbol"),
                        "expiry": exp_str,
                        "strike": trade.get("strike"),
                        "option_type": trade.get("option_type"),
                        "exit_price": exit_price,
                        "underlying_price": underlying_price,
                        "pnl": closed_trade.get("pnl", 0.0),
                        "net_pnl": closed_trade.get("net_pnl", 0.0),
                        "closed_by": "EXPIRY_SETTLEMENT",
                    },
                    "timestamp": now_utc,
                }
                await db.audit_logs.insert_one(audit_entry)
                settled_trades.append(trade_id)
                logger.info(
                    f"[Settlement] Settled trade {trade_id} at ₹{exit_price} "
                    f"(underlying=₹{underlying_price}, pnl=₹{closed_trade.get('pnl')})"
                )

    return {
        "status": "success",
        "settled_trades_count": len(settled_trades),
        "settled_trades": settled_trades,
        "cancelled_orders_count": len(cancelled_orders),
        "cancelled_orders": cancelled_orders,
        "retry_trades_count": len(retry_trades),
    }


async def start_settlement_engine(interval_seconds: float = 60.0):
    """Continuous background loop running settlement cycle every interval_seconds."""
    logger.info("Settlement Engine started (Contract expiry loop, 60s cycle).")
    while True:
        try:
            await run_settlement_cycle()
        except asyncio.CancelledError:
            logger.info("Settlement Engine cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in Settlement Engine cycle: {e}", exc_info=True)

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Settlement Engine sleep cancelled.")
            break
