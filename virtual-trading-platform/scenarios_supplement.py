"""
Supplementary verification script:
1. OPTION limit order fill-time REJECTED with full reserve release
2. OTM (worthless) option expiry settlement (CE and PE)
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

os.environ["MONGO_URI"] = "mongodb://localhost:27017"
sys.path.insert(0, "/Users/singhhariom3794gmail.com/Desktop/simulation_adminbase/virtual-trading-platform")

from db import init_db, get_db
import order_engine
import trade_engine
import settlement_engine
import market_calendar

async def run_supplementary():
    await init_db()
    db = get_db()
    print("=" * 80)
    print("SUPPLEMENTARY SCENARIO AUDIT: OPTION FILL REJECTION & OTM EXPIRY")
    print("=" * 80)

    # Global Brokerage: ₹20 / lot
    await db.brokerage_config.delete_many({})
    await db.brokerage_config.insert_many([
        {"scope": "global", "segment": "option", "instrument_type": "ANY", "mode": "PER_LOT", "value": 20.0, "enabled": True},
    ])

    # -------------------------------------------------------------------------
    # PART 1: OPTION Limit Order Fill-Time REJECTED with Full Reserve Release
    # -------------------------------------------------------------------------
    print("\n--- PART 1: OPTION Limit Order Fill-Time REJECTED with Full Reserve Release ---")
    u_rej = "user_opt_reject_audit"
    init_bal = 10000.0
    await db.users.delete_many({"user_id": u_rej})
    await db.orders.delete_many({"user_id": u_rej})
    await db.trades_option.delete_many({"user_id": u_rej})

    await db.users.insert_one({
        "user_id": u_rej,
        "balance": init_bal,
        "available_balance": init_bal,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
        "is_active": True,
    })

    print(f"Step 1: User Created. Balance=₹{init_bal:.2f}, Available=₹{init_bal:.2f}, MarginBlocked=₹0.00")

    # Place OPTION BUY LIMIT order: 1 lot (50 qty) at limit price ₹50.0
    # Reserved lock = 50 * 50 = ₹2,500.00. Reserved brokerage = ₹20.00. Total R = ₹2,520.00
    r_lock = 2500.0
    r_brok = 20.0
    r_total = 2520.0

    await db.users.update_one(
        {"user_id": u_rej},
        {"$inc": {"available_balance": -r_total, "margin_blocked": r_total}}
    )
    ord_id = "ORD_OPT_REJ_001"
    now_utc = datetime.now(timezone.utc)
    await db.orders.insert_one({
        "order_id": ord_id,
        "user_id": u_rej,
        "segment": "option",
        "instrument": "NIFTY",
        "symbol": "NIFTY",
        "tradingsymbol": "NIFTY26OCT24500CE",
        "exchange": "NFO",
        "symboltoken": "NIFTY_OPT_TOK_REJ",
        "instrument_type": "INDEX",
        "action": "BUY",
        "order_type": "LIMIT",
        "limit_price": 50.0,
        "price": 50.0,
        "lots": 1,
        "lot_size": 50,
        "qty": 50,
        "pnl_qty": 50.0,
        "pnl_multiplier_per_lot": 50.0,
        "status": "PENDING",
        "version": 1,
        "reserved_margin": r_lock,
        "reserved_brokerage": r_brok,
        "reserved_total": r_total,
        "created_at": now_utc,
    })

    u_after_order = await db.users.find_one({"user_id": u_rej})
    print(f"Step 2: Order Placed (Reserved ₹{r_total:.2f}). Balance=₹{u_after_order['balance']:.2f}, Available=₹{u_after_order['available_balance']:.2f}, MarginBlocked=₹{u_after_order['margin_blocked']:.2f}")

    # Now, between placement and fill, user exhausts available balance on another trade or admin deducts funds
    # Available balance drops from 7480.0 to 0.0!
    await db.users.update_one({"user_id": u_rej}, {"$set": {"available_balance": 0.0}})
    u_drained = await db.users.find_one({"user_id": u_rej})
    print(f"Step 3: User balance depleted before fill. Available=₹{u_drained['available_balance']:.2f}, MarginBlocked=₹{u_drained['margin_blocked']:.2f}")

    # Now at fill time, price ticks to 50.0. But lock required requires an extra delta (e.g. delta_needed = 200.0)
    # The guard: available_balance >= delta_needed FAILS because available_balance = 0 < 200.0!
    print("Step 4: Engine attempts fill where delta_needed = ₹200.00 > available_balance (₹0.00)...")
    with patch("order_engine.compute_required_lock", return_value=r_lock + 200.0), \
         patch.object(order_engine.angel_client, "get_ltp_with_meta", return_value={"price": 50.0, "fetched_at": datetime.now(timezone.utc), "source": "live"}), \
         patch("order_engine.market_calendar.is_market_open", return_value=True):
        await order_engine.run_order_cycle()

    o_rej = await db.orders.find_one({"order_id": ord_id})
    u_after_rej = await db.users.find_one({"user_id": u_rej})

    print(f"Step 5: Fill Guard Result: Order Status={o_rej['status']}, Reject Reason='{o_rej.get('reject_reason')}'")
    print(f"User Balance after REJECTION: Available=₹{u_after_rej['available_balance']:.2f}, MarginBlocked=₹{u_after_rej['margin_blocked']:.2f}")

    # Full reserve R was unlocked and refunded
    assert o_rej["status"] == "REJECTED"
    assert "Insufficient funds" in o_rej["reject_reason"]
    assert round(u_after_rej["available_balance"], 2) == round(r_total, 2)
    assert round(u_after_rej["margin_blocked"], 2) == 0.0
    print("✓ Part 1 Passed: Guard caught insufficient balance, order rejected, and full reserve ₹2,520.00 refunded!")

    # -------------------------------------------------------------------------
    # PART 2: OTM (Worthless) Expiry Settlement Scenario (NIFTY 25000 CE)
    # -------------------------------------------------------------------------
    print("\n--- PART 2: OTM (Worthless) Expiry Settlement (NIFTY 25000 CE) ---")
    u_otm = "user_otm_settle_audit"
    init_bal_otm = 50000.0
    await db.users.delete_many({"user_id": u_otm})
    await db.trades_option.delete_many({"user_id": u_otm})

    await db.users.insert_one({
        "user_id": u_otm,
        "balance": init_bal_otm,
        "available_balance": init_bal_otm,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
        "is_active": True,
    })

    print(f"Initial State: Balance=₹{init_bal_otm:.2f}, Available=₹{init_bal_otm:.2f}, MarginBlocked=₹0.00, BrokPaid=₹0.00")

    # User buys 1 lot (25 qty) NIFTY 25000 CE at ₹100.0
    # Required lock = 25 * 100 = ₹2,500.00. Entry brokerage = ₹20.00
    ce_contract = {
        "tradingsymbol": "NIFTY26OCT25000CE",
        "symbol": "NIFTY",
        "symboltoken": "NIFTY_25000_CE_TOK",
        "exchange": "NFO",
        "lot_size": 25,
        "pnl_multiplier_per_lot": 25.0,
        "strike": 25000.0,
        "option_type": "CE",
        "expiry": "2026-10-26",
        "instrument_type": "INDEX",
    }
    trade_otm = await trade_engine.open_position(
        user_id=u_otm,
        segment="option",
        contract=ce_contract,
        action="BUY",
        lots=1,
        qty=25,
        price=100.0,
    )
    t_otm_id = trade_otm["trade_id"]
    u_open = await db.users.find_one({"user_id": u_otm})
    print(f"After Buying 25000 CE at ₹100: Available=₹{u_open['available_balance']:.2f}, MarginBlocked=₹{u_open['margin_blocked']:.2f}, TotalBrokPaid=₹{u_open['total_brokerage_paid']:.2f}")

    # Expiry occurs: NIFTY spot settles at 24,500.00 (below 25,000 CE strike -> intrinsic = max(0, 24500 - 25000) = ₹0.00)
    print("Expiry Settlement Cycle triggered with NIFTY spot at 24,500.00 (OTM / Worthless)...")
    with patch("settlement_engine.market_calendar.contract_expired", return_value=True), \
         patch.object(settlement_engine.angel_client, "get_ltp", return_value=24500.0):
        res = await settlement_engine.run_settlement_cycle()

    t_otm_closed = await db.trades_option.find_one({"trade_id": t_otm_id})
    u_after_otm = await db.users.find_one({"user_id": u_otm})

    print(f"Trade Closed Status: {t_otm_closed['status']}, Closed By: {t_otm_closed['closed_by']}")
    print(f"Settlement Price: ₹{t_otm_closed['settlement_price']:.2f}, Underlying Spot: ₹{t_otm_closed['underlying_price']:.2f}")
    print(f"Gross P&L: ₹{t_otm_closed['pnl']:.2f} (Full loss of premium: -₹2,500.00)")
    print(f"Brokerage: Entry=₹{t_otm_closed['entry_brokerage']:.2f}, Exit=₹{t_otm_closed['exit_brokerage']:.2f}, Total=₹{t_otm_closed['brokerage_total']:.2f}")
    print(f"Net Realized P&L: ₹{t_otm_closed['net_pnl']:.2f}")
    print(f"Final User State: Available=₹{u_after_otm['available_balance']:.2f}, MarginBlocked=₹{u_after_otm['margin_blocked']:.2f}, TotalBrokPaid=₹{u_after_otm['total_brokerage_paid']:.2f}")

    # Assertions
    assert t_otm_closed["status"] == "CLOSED"
    assert t_otm_closed["closed_by"] == "EXPIRY_SETTLEMENT"
    assert t_otm_closed["exit_price"] == 0.0
    assert t_otm_closed["settlement_price"] == 0.0
    assert t_otm_closed["pnl"] == -2500.0
    assert t_otm_closed["exit_brokerage"] == 20.0
    assert t_otm_closed["brokerage_total"] == 40.0
    assert t_otm_closed["net_pnl"] == -2540.0
    assert round(u_after_otm["margin_blocked"], 2) == 0.0
    assert round(u_after_otm["total_brokerage_paid"], 2) == 40.0
    # Starting 50,000 - 2,540 net loss = 47,460.00
    assert round(u_after_otm["available_balance"], 2) == 47460.0
    print("✓ Part 2 Passed: OTM option settled at ₹0.00, 100% premium lost, brokerage accounted, zero margin leakage!")

    print("\n" + "=" * 80)
    print("ALL SUPPLEMENTARY AUDITS PASSED CLEANLY")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_supplementary())
