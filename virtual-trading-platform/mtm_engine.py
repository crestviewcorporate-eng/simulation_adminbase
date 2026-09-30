import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from db import get_db
from angelone_client import angel_client, BadSymbolTokenError

logger = logging.getLogger("virtual_trading.mtm_engine")


async def _close_single_trade(
    segment: str,
    trade: Dict[str, Any],
    exit_price: float,
    closed_by: str = "SYSTEM_AUTO_SQUARE_OFF",
) -> Optional[Dict[str, Any]]:
    """Atomically closes a single trade across any segment (option, future, cash):
    1. Validates that a positive real exit price exists.
    2. Transitions status OPEN -> CLOSED via atomic find_one_and_update.
    3. Releases margin_blocked_amount and credits/debits realized P&L to user available_balance unconditionally.
    4. Returns updated trade doc, or None if already closed (prevents race condition).
    """
    if exit_price is None or exit_price < 0 or (exit_price == 0 and closed_by != "EXPIRY_SETTLEMENT"):
        raise ValueError(f"Invalid exit price '{exit_price}' for trade {trade.get('trade_id')}")

    db = get_db()
    coll_name = f"trades_{segment}"
    trade_id = trade["trade_id"]
    user_id = trade["user_id"]

    entry_price = float(trade.get("entry_price", 0.0))
    pnl_qty = float(trade.get("pnl_qty", trade.get("qty", 1)))
    lots = int(trade.get("lots", 1))
    action = trade.get("action", "BUY").upper()
    multiplier = 1.0 if action == "BUY" else -1.0

    gross_pnl = round((exit_price - entry_price) * pnl_qty * multiplier, 2)
    entry_brokerage = float(trade.get("entry_brokerage", 0.0))

    # Resolve exit brokerage snapshot
    from trade_engine import resolve_brokerage_config, compute_brokerage
    from scrip_master import scrip_master
    inst_type = trade.get("instrument_type") or scrip_master.get_instrument_type(trade.get("instrument", ""))
    exit_cfg = await resolve_brokerage_config(
        user_id=user_id,
        segment=segment,
        instrument_type=inst_type,
    )
    exit_brokerage = compute_brokerage(
        config=exit_cfg,
        price=exit_price,
        lots=lots,
        pnl_qty=pnl_qty,
    )
    brokerage_total = round(entry_brokerage + exit_brokerage, 2)
    net_pnl = round(gross_pnl - brokerage_total, 2)

    now = datetime.now(timezone.utc)

    # 1. Atomically transition trade status from OPEN to CLOSED
    from pymongo import ReturnDocument
    update_doc = {
        "status": "CLOSED",
        "exit_price": exit_price,
        "exit_time": now,
        "pnl": gross_pnl,  # Preserved as GROSS for UI and existing tests
        "entry_brokerage": entry_brokerage,
        "exit_brokerage": exit_brokerage,
        "brokerage_total": brokerage_total,
        "net_pnl": net_pnl,
        "closed_by": closed_by,
        "updated_at": now,
    }
    if "settlement_price" in trade:
        update_doc["settlement_price"] = trade["settlement_price"]
    if "underlying_price" in trade:
        update_doc["underlying_price"] = trade["underlying_price"]

    updated_trade = await db[coll_name].find_one_and_update(
        {"trade_id": trade_id, "status": "OPEN"},
        {"$set": update_doc},
        return_document=ReturnDocument.AFTER,
    )

    # If already closed by another concurrent caller/engine, exit cleanly without double processing
    if not updated_trade:
        return None

    # 2. Release margin & apply realized net delta atomically across ALL segments
    margin_blocked_amount = float(updated_trade.get("margin_blocked_amount", trade.get("margin_blocked_amount", 0.0)))
    balance_credit = margin_blocked_amount + gross_pnl - exit_brokerage
    realized_delta = gross_pnl - exit_brokerage

    await db.users.update_one(
        {"user_id": user_id},
        {
            "$inc": {
                "available_balance": balance_credit,
                "margin_blocked": -margin_blocked_amount,
                "realized_pnl": realized_delta,
                "total_brokerage_paid": exit_brokerage,
            },
            "$set": {
                "updated_at": now,
            },
        },
    )

    updated_trade.pop("_id", None)
    return updated_trade


async def run_mtm_cycle():
    """Execute a single MTM cycle across all active users with open positions across all segments.

    Optimizations & Strict Price Rules:
    - Deduplicates API calls: multiple trades sharing the same symboltoken make only ONE live fetch.
    - Real broker prices only: NO fallback to synthetic or entry_price.
    - Bad/expired tokens: marked needs_settlement=True on the trade doc; no price substituted.
    - Missing prices: keeps user's last good unrealized/equity values, sets mtm_stale=True, skips auto square-off.
    - Complete cycle: clears mtm_stale=False on next complete cycle with all fresh prices.
    """
    db = get_db()

    # 1. Collect all distinct user_ids with at least one OPEN trade
    user_ids_set: set = set()
    for seg in ("option", "future", "cash"):
        active_ids = await db[f"trades_{seg}"].distinct("user_id", {"status": "OPEN"})
        user_ids_set.update(active_ids)

    if not user_ids_set:
        return

    now = datetime.now(timezone.utc)

    # 2. Build a global token→LTP map for ALL open trades across ALL users (deduplicated)
    token_to_ltp: Dict[str, float] = {}  # key: "EXCHANGE:TOKEN"
    bad_expired_tokens: set = set()

    all_trades_by_user: Dict[str, List[Dict[str, Any]]] = {}
    for user_id in user_ids_set:
        trades: List[Dict[str, Any]] = []
        for seg in ("option", "future", "cash"):
            seg_trades = await db[f"trades_{seg}"].find(
                {"user_id": user_id, "status": "OPEN"}
            ).to_list(length=1000)
            for t in seg_trades:
                t["_segment"] = seg
            trades.extend(seg_trades)
        all_trades_by_user[user_id] = trades

    # Collect unique tokens across all users
    unique_tokens: Dict[str, Dict] = {}  # "EXCHANGE:TOKEN" -> {exchange, tradingsymbol, symboltoken}
    for trades in all_trades_by_user.values():
        for t in trades:
            exch  = t.get("exchange", "NSE")
            sym   = t.get("tradingsymbol", t.get("instrument", ""))
            token = str(t.get("symboltoken", ""))
            if token and token not in ("", "0", "None"):
                key = f"{exch}:{token}"
                if key not in unique_tokens:
                    unique_tokens[key] = {"exchange": exch, "tradingsymbol": sym, "symboltoken": token}

    # Fetch LTP once per unique token
    for key, inst in unique_tokens.items():
        try:
            ltp = angel_client.get_ltp(
                exchange=inst["exchange"],
                tradingsymbol=inst["tradingsymbol"],
                symboltoken=inst["symboltoken"],
            )
            if ltp and ltp > 0:
                token_to_ltp[key] = ltp
        except Exception as ex:
            err_str = str(ex).lower()
            is_bad = isinstance(ex, BadSymbolTokenError) or any(
                k in err_str for k in ("bad/expired token", "ab4046", "token not found", "symbol token not found")
            )
            if is_bad:
                bad_expired_tokens.add(key)
                logger.warning(f"[MTM] Bad/expired token detected for {key} ({inst['tradingsymbol']}): {ex}")
            elif "rate limit" in err_str or "exceeding access rate" in err_str:
                logger.warning(f"[MTM] Rate-limited fetching {key}: {ex}")
            else:
                logger.warning(f"[MTM] LTP fetch failed for {key} ({inst['tradingsymbol']}): {ex}")
            # token_to_ltp[key] stays absent - NO synthetic price is substituted!

    # 3. For each user, compute MTM using the pre-fetched token map
    for user_id in user_ids_set:
        try:
            all_open_trades = all_trades_by_user.get(user_id, [])
            if not all_open_trades:
                continue

            has_missing_price = False
            total_unrealized = 0.0
            trade_ltps: Dict[str, float] = {}

            for t in all_open_trades:
                seg   = t["_segment"]
                exch  = t.get("exchange", "NSE")
                token = str(t.get("symboltoken", ""))
                key   = f"{exch}:{token}"

                # Check if trade is past expiry cutoff
                exp_str = t.get("expiry")
                import market_calendar
                if exp_str and market_calendar.contract_expired(exch, exp_str, market_calendar.now_ist()):
                    logger.info(
                        f"[MTM] Trade {t['trade_id']} past expiry cutoff {exp_str}. "
                        f"Setting needs_settlement=True and excluding from live loss%."
                    )
                    await db[f"trades_{seg}"].update_one(
                        {"trade_id": t["trade_id"]},
                        {"$set": {"needs_settlement": True, "updated_at": now}},
                    )
                    continue

                # Bad/expired token: mark needs_settlement=True on trade, do not substitute price
                if key in bad_expired_tokens:
                    logger.warning(
                        f"[MTM] Trade {t['trade_id']} has bad/expired token {token}. "
                        f"Setting needs_settlement=True (no price substituted)."
                    )
                    await db[f"trades_{seg}"].update_one(
                        {"trade_id": t["trade_id"]},
                        {"$set": {"needs_settlement": True, "updated_at": now}},
                    )
                    has_missing_price = True
                    continue

                ltp = token_to_ltp.get(key)
                if ltp is None or ltp <= 0:
                    logger.warning(
                        f"[MTM] Missing fresh price for token {key} ({t.get('tradingsymbol')}) on trade {t['trade_id']}."
                    )
                    has_missing_price = True
                    continue

                entry = float(t.get("entry_price", 0.0))
                pnl_qty = float(t.get("pnl_qty", t.get("qty", 1)))
                action = t.get("action", "BUY").upper()
                multiplier = 1.0 if action == "BUY" else -1.0

                trade_ltps[t["trade_id"]] = ltp
                unrealized = (ltp - entry) * pnl_qty * multiplier
                total_unrealized += unrealized

            # If any open position has no fresh price:
            # Keep user's last good unrealized/equity values, set mtm_stale=True, and skip auto square-off
            if has_missing_price:
                logger.warning(
                    f"[MTM] User '{user_id}' has open positions with missing/stale prices. "
                    f"Keeping last good unrealized/equity values, setting mtm_stale=True, and skipping auto square-off."
                )
                await db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "mtm_stale": True,
                            "mtm_updated_at": now,
                            "updated_at": now,
                        }
                    },
                )
                continue

            # Complete cycle with all fresh prices: clear mtm_stale
            total_unrealized = round(total_unrealized, 2)

            # Fetch fresh user document
            user = await db.users.find_one({"user_id": user_id})
            if not user:
                continue

            balance = float(user.get("balance", 0.0))
            realized_pnl = float(user.get("realized_pnl", 0.0))
            equity = round(balance + realized_pnl + total_unrealized, 2)

            if balance > 0:
                loss_pct = round(max(0.0, (balance - equity) / balance * 100.0), 2)
            else:
                loss_pct = 0.0

            # Update user doc with live cached MTM metrics and clear mtm_stale
            await db.users.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "unrealized_pnl": total_unrealized,
                        "equity": equity,
                        "loss_pct": loss_pct,
                        "mtm_stale": False,
                        "mtm_updated_at": now,
                        "updated_at": now,
                    }
                },
            )

            # Check Auto Square-off Condition
            threshold_pct = float(user.get("auto_square_off_pct", 80.0))
            last_auto_close = user.get("last_auto_square_off_at")

            # Avoid immediate re-trigger within last 10 seconds
            is_cooling_down = False
            if last_auto_close:
                if isinstance(last_auto_close, datetime):
                    if last_auto_close.tzinfo is None:
                        last_auto_close = last_auto_close.replace(tzinfo=timezone.utc)
                    if (now - last_auto_close).total_seconds() < 10:
                        is_cooling_down = True

            if loss_pct >= threshold_pct and not is_cooling_down and len(all_open_trades) > 0:
                logger.warning(
                    f"Auto square-off triggered for user '{user_id}': loss_pct={loss_pct}% >= threshold={threshold_pct}%"
                )
                from order_engine import cancel_all_user_pending_orders
                await cancel_all_user_pending_orders(user_id, cancelled_by="SYSTEM_AUTO_SQUARE_OFF")

                closed_counts = {"option": 0, "future": 0, "cash": 0}
                for trade in all_open_trades:
                    seg = trade["_segment"]
                    ltp = trade_ltps.get(trade["trade_id"])
                    if not ltp or ltp <= 0:
                        continue
                    closed = await _close_single_trade(
                        segment=seg,
                        trade=trade,
                        exit_price=ltp,
                        closed_by="SYSTEM_AUTO_SQUARE_OFF",
                    )
                    if closed and seg in closed_counts:
                        closed_counts[seg] += 1

                # Update last_auto_square_off_at on user
                await db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "last_auto_square_off_at": now,
                            "unrealized_pnl": 0.0,
                            "updated_at": now,
                        }
                    },
                )

                # Write audit log with per-segment breakdown
                audit_doc = {
                    "log_id": f"AUD-SYS-{uuid.uuid4().hex[:8].upper()}",
                    "admin_id": "SYSTEM",
                    "actor": "SYSTEM",
                    "action": "AUTO_SQUARE_OFF",
                    "target_user_id": user_id,
                    "details": {
                        "loss_pct": loss_pct,
                        "threshold_pct": threshold_pct,
                        "equity": equity,
                        "balance": balance,
                        "trades_closed": closed_counts,
                    },
                    "timestamp": now,
                }
                await db.audit_logs.insert_one(audit_doc)

        except Exception as e:
            logger.error(f"Error processing MTM cycle for user '{user_id}': {e}", exc_info=True)


async def start_mtm_engine(interval_seconds: float = 15.0):
    """Continuous background loop running MTM cycle every interval_seconds.

    Default 15s gives ~4 cycles/min. With N unique instruments, each cycle costs
    N × MIN_API_INTERVAL seconds of broker time. 15s safely accommodates up to 10
    unique instruments without triggering AngelOne rate limits.
    """
    logger.info("MTM & Risk Management Background Engine started (Unified Multi-Segment Mode, 15s cycle).")
    while True:
        try:
            await run_mtm_cycle()
        except asyncio.CancelledError:
            logger.info("MTM Background Engine cancelled.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in MTM cycle: {e}", exc_info=True)

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("MTM Background Engine sleep cancelled.")
            break
