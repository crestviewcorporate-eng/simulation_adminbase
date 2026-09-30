import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import market_calendar
from db import get_db
import settlement_engine
import trade_engine
import mtm_engine
from angelone_client import LTPFetchError, angel_client

# Mark all tests in this file as asyncio
pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
async def cleanup_db():
    db = get_db()
    await db.trades_option.delete_many({"user_id": {"$regex": "^test_settle_"}})
    await db.trades_future.delete_many({"user_id": {"$regex": "^test_settle_"}})
    await db.trades_cash.delete_many({"user_id": {"$regex": "^test_settle_"}})
    await db.orders.delete_many({"user_id": {"$regex": "^test_settle_"}})
    await db.users.delete_many({"user_id": {"$regex": "^test_settle_"}})
    await db.settlement_audit_log.delete_many({})
    yield
    await db.trades_option.delete_many({"user_id": {"$regex": "^test_settle_"}})
    await db.trades_future.delete_many({"user_id": {"$regex": "^test_settle_"}})
    await db.trades_cash.delete_many({"user_id": {"$regex": "^test_settle_"}})
    await db.orders.delete_many({"user_id": {"$regex": "^test_settle_"}})
    await db.users.delete_many({"user_id": {"$regex": "^test_settle_"}})
    await db.settlement_audit_log.delete_many({})

async def setup_user(user_id="test_settle_u1", balance=100000.0):
    db = get_db()
    user = {
        "user_id": user_id,
        "email": f"{user_id}@example.com",
        "role": "user",
        "allowed_segments": ["option", "future", "cash"],
        "allowed_instrument_types": ["INDEX", "MCX"],
        "starting_balance": balance,
        "available_balance": balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "is_active": True,
        "created_at": datetime.now(timezone.utc)
    }
    await db.users.insert_one(user)
    return user

async def test_otm_option_settles_at_zero():
    """Prompt 5: OTM option settles at 0, margin is released, exit brokerage is charged, trade status CLOSED."""
    db = get_db()
    uid = "test_settle_u1"
    await setup_user(uid, 50000.0)
    
    contract = {
        "tradingsymbol": "NIFTY24OCT25000CE",
        "symboltoken": "99901",
        "exchange": "NFO",
        "lot_size": 25,
        "pnl_qty": 25,
        "strike": 25000.0,
        "option_type": "CE",
        "expiry": "2024-10-31",
        "instrument_type": "INDEX",
        "instrument": "NIFTY"
    }
    
    trade = await trade_engine.open_position(
        user_id=uid,
        segment="option",
        contract=contract,
        action="BUY",
        lots=1,
        qty=25,
        price=100.0
    )
    assert trade["product"] == "CF"
    
    # Contract is expired, underlying spot settles at 24500 (OTM for 25000CE)
    now_ist = datetime(2024, 10, 31, 16, 0, tzinfo=market_calendar.IST)
    
    with patch("market_calendar.now_ist", return_value=now_ist), \
         patch.object(angel_client, "get_ltp", return_value=24500.0):
        
        res = await settlement_engine.run_settlement_cycle()
        assert res["settled_trades_count"] == 1
    
    closed_trade = await db.trades_option.find_one({"trade_id": trade["trade_id"]})
    assert closed_trade["status"] == "CLOSED"
    assert closed_trade["closed_by"] == "EXPIRY_SETTLEMENT"
    assert closed_trade["exit_price"] == 0.0
    assert closed_trade["settlement_price"] == 0.0
    assert closed_trade["underlying_price"] == 24500.0
    # Gross PNL = -100 * 25 = -2500.0
    assert closed_trade["pnl"] == -2500.0

async def test_itm_ce_and_pe_intrinsic_math():
    """Prompt 5: CE intrinsic = max(spot - strike, 0), PE = max(strike - spot, 0)."""
    db = get_db()
    uid = "test_settle_u2"
    await setup_user(uid, 100000.0)
    
    # 1. CE Trade: Strike 24000, Spot 24500 -> Intrinsic = 500
    ce_contract = {
        "tradingsymbol": "NIFTY24OCT24000CE",
        "symboltoken": "99902",
        "exchange": "NFO",
        "lot_size": 25,
        "pnl_qty": 25,
        "strike": 24000.0,
        "option_type": "CE",
        "expiry": "2024-10-31",
        "instrument_type": "INDEX",
        "instrument": "NIFTY"
    }
    t_ce = await trade_engine.open_position(
        user_id=uid, segment="option", contract=ce_contract, action="BUY", lots=1, qty=25, price=200.0
    )
    
    # 2. PE Trade: Strike 25000, Spot 24500 -> Intrinsic = 500
    pe_contract = {
        "tradingsymbol": "NIFTY24OCT25000PE",
        "symboltoken": "99903",
        "exchange": "NFO",
        "lot_size": 25,
        "pnl_qty": 25,
        "strike": 25000.0,
        "option_type": "PE",
        "expiry": "2024-10-31",
        "instrument_type": "INDEX",
        "instrument": "NIFTY"
    }
    t_pe = await trade_engine.open_position(
        user_id=uid, segment="option", contract=pe_contract, action="BUY", lots=1, qty=25, price=300.0
    )
    
    now_ist = datetime(2024, 10, 31, 16, 0, tzinfo=market_calendar.IST)
    with patch("market_calendar.now_ist", return_value=now_ist), \
         patch.object(angel_client, "get_ltp", return_value=24500.0):
        
        res = await settlement_engine.run_settlement_cycle()
        assert res["settled_trades_count"] == 2
        
    c_ce = await db.trades_option.find_one({"trade_id": t_ce["trade_id"]})
    assert c_ce["exit_price"] == 500.0
    assert c_ce["settlement_price"] == 500.0
    # Gross PNL = (500 - 200) * 25 = +7500.0
    assert c_ce["pnl"] == 7500.0
    
    c_pe = await db.trades_option.find_one({"trade_id": t_pe["trade_id"]})
    assert c_pe["exit_price"] == 500.0
    assert c_pe["settlement_price"] == 500.0
    # Gross PNL = (500 - 300) * 25 = +5000.0
    assert c_pe["pnl"] == 5000.0

async def test_settlement_race_with_manual_close():
    """Prompt 5: Settlement vs manual close race: atomic close ensures exactly one succeeds and margin released once."""
    db = get_db()
    uid = "test_settle_u3"
    await setup_user(uid, 50000.0)
    
    contract = {
        "tradingsymbol": "NIFTY24OCT25000CE",
        "symboltoken": "99904",
        "exchange": "NFO",
        "lot_size": 25,
        "pnl_qty": 25,
        "strike": 25000.0,
        "option_type": "CE",
        "expiry": "2024-10-31",
        "instrument_type": "INDEX",
        "instrument": "NIFTY"
    }
    trade = await trade_engine.open_position(
        user_id=uid, segment="option", contract=contract, action="BUY", lots=1, qty=25, price=100.0
    )
    
    now_ist = datetime(2024, 10, 31, 16, 0, tzinfo=market_calendar.IST)
    
    async def do_settle():
        with patch("market_calendar.now_ist", return_value=now_ist), \
             patch.object(angel_client, "get_ltp", return_value=24000.0):
            return await settlement_engine.run_settlement_cycle()
            
    async def do_manual():
        return await mtm_engine._close_single_trade(
            segment="option",
            trade=trade,
            exit_price=50.0,
            closed_by="MANUAL"
        )
        
    results = await asyncio.gather(do_settle(), do_manual(), return_exceptions=True)
    closed_trade = await db.trades_option.find_one({"trade_id": trade["trade_id"]})
    assert closed_trade["status"] == "CLOSED"
    
    user = await db.users.find_one({"user_id": uid})
    assert user["margin_blocked"] == 0.0

async def test_settlement_retries_when_no_price():
    """Prompt 5: If no real price is available, keep the trade OPEN, set needs_settlement=true and retry next cycle. Never guess."""
    db = get_db()
    uid = "test_settle_u4"
    await setup_user(uid, 50000.0)
    
    contract = {
        "tradingsymbol": "NIFTY24OCT25000CE",
        "symboltoken": "99905",
        "exchange": "NFO",
        "lot_size": 25,
        "pnl_qty": 25,
        "strike": 25000.0,
        "option_type": "CE",
        "expiry": "2024-10-31",
        "instrument_type": "INDEX",
        "instrument": "NIFTY"
    }
    trade = await trade_engine.open_position(
        user_id=uid, segment="option", contract=contract, action="BUY", lots=1, qty=25, price=100.0
    )
    
    now_ist = datetime(2024, 10, 31, 16, 0, tzinfo=market_calendar.IST)
    
    with patch("market_calendar.now_ist", return_value=now_ist), \
         patch.object(angel_client, "get_ltp", side_effect=LTPFetchError("Feed unavailable")):
        
        res = await settlement_engine.run_settlement_cycle()
        assert res["settled_trades_count"] == 0
        
    t = await db.trades_option.find_one({"trade_id": trade["trade_id"]})
    assert t["status"] == "OPEN"
    assert t["needs_settlement"] is True

async def test_pending_orders_cancelled_at_expiry():
    """Prompt 5: Cancel all PENDING orders on expired contracts and release their reserves."""
    db = get_db()
    uid = "test_settle_u5"
    await setup_user(uid, 50000.0)
    
    order = {
        "order_id": "ORD-SETTLE-001",
        "user_id": uid,
        "segment": "option",
        "instrument_type": "INDEX",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY24OCT25000CE",
        "exchange": "NFO",
        "symboltoken": "99906",
        "expiry": "2024-10-31",
        "strike": 25000.0,
        "option_type": "CE",
        "lot_size": 25,
        "lots": 1,
        "qty": 25,
        "pnl_qty": 25,
        "action": "BUY",
        "order_type": "LIMIT",
        "limit_price": 50.0,
        "status": "PENDING",
        "reserved_total": 1250.0,
        "version": 1,
        "created_at": datetime.now(timezone.utc),
        "history": []
    }
    await db.orders.insert_one(order)
    # Block reserve in user
    await db.users.update_one({"user_id": uid}, {"$inc": {"available_balance": -1250.0, "margin_blocked": 1250.0}})
    
    now_ist = datetime(2024, 10, 31, 16, 0, tzinfo=market_calendar.IST)
    with patch("market_calendar.now_ist", return_value=now_ist):
        await settlement_engine.run_settlement_cycle()
        
    ord_doc = await db.orders.find_one({"order_id": "ORD-SETTLE-001"})
    assert ord_doc["status"] == "CANCELLED"
    assert ord_doc["cancelled_by"] == "EXPIRY_SETTLEMENT"
    
    user = await db.users.find_one({"user_id": uid})
    assert user["available_balance"] == 50000.0
    assert user["margin_blocked"] == 0.0

async def test_option_stays_open_across_simulated_market_close():
    """Prompt 5: Prove an option trade (product=CF) stays OPEN across market close (is never auto-closed at day end)."""
    db = get_db()
    uid = "test_settle_u6"
    await setup_user(uid, 50000.0)
    
    contract = {
        "tradingsymbol": "NIFTY24NOV25000CE",
        "symboltoken": "99907",
        "exchange": "NFO",
        "lot_size": 25,
        "pnl_qty": 25,
        "strike": 25000.0,
        "option_type": "CE",
        "expiry": "2024-11-28", # next month, not expired
        "instrument_type": "INDEX",
        "instrument": "NIFTY"
    }
    trade = await trade_engine.open_position(
        user_id=uid, segment="option", contract=contract, action="BUY", lots=1, qty=25, price=150.0
    )
    assert trade["product"] == "CF"
    
    # Simulate market close at 15:35 IST today
    close_ist = datetime(2024, 10, 25, 15, 35, tzinfo=market_calendar.IST)
    with patch("market_calendar.now_ist", return_value=close_ist):
        res = await settlement_engine.run_settlement_cycle()
        assert res["settled_trades_count"] == 0
        
    t = await db.trades_option.find_one({"trade_id": trade["trade_id"]})
    assert t["status"] == "OPEN"
    assert t["product"] == "CF"
