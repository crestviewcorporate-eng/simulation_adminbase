"""Tests for Market Calendar, IST Cutoff Rollover, and MCX Futures Pipeline.
Covers:
  1. Nearest-expiry rollover using a mocked clock (before and after expiry-day cutoff).
  2. GOLD 1 lot ₹100 move = ₹10,000 P&L (lots * pnl_multiplier_per_lot).
  3. Unconfigured MCX margin rejected with exact message ("Margin not configured for <symbol>, admin must set it").
  4. User without MCX permission gets 403 Forbidden.
  5. Market closed rejection ("Market closed for <exchange>").
  6. NIFTY behavior unchanged.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient

from auth import create_access_token
from db import get_db
from main import app
from market_calendar import contract_expired, is_market_open, IST
from scrip_master import scrip_master, COMMODITY_CONFIGS, INDEX_CONFIGS
from mtm_engine import _close_single_trade

MOCK_WEDNESDAY_OPEN = datetime(2026, 9, 30, 11, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
async def setup_test_users():
    db = get_db()
    test_prefix = "mcx_test_"
    await db.users.delete_many({"user_id": {"$regex": f"^{test_prefix}"}})
    for seg in ["option", "future", "cash"]:
        await db[f"trades_{seg}"].delete_many({"user_id": {"$regex": f"^{test_prefix}"}})
    await db.instrument_margins.delete_many({"symbol": {"$in": ["GOLD", "GOLDM", "CRUDEOIL", "SILVER"]}})
    await db.brokerage_config.delete_many({})
    yield


# ---------------------------------------------------------------------------
# 1. Nearest-expiry rollover using mocked clock (before and after cutoff)
# ---------------------------------------------------------------------------
async def test_01_nearest_expiry_rollover_before_and_after_cutoff():
    """Verify that a contract on its expiry day is active at 15:29 IST and rolls at 15:31 IST."""
    scrip_master.ensure_loaded()
    
    # Test NSE Expiry: NIFTY cutoff is 15:30 IST
    expiries_raw = scrip_master.get_expiries("NIFTY", "future")
    assert len(expiries_raw) > 0, "NIFTY future expiries must be available in scrip master"
    target_exp_str = expiries_raw[0]["expiry"]
    target_date = datetime.strptime(target_exp_str, "%d%b%Y").date()

    # Before cutoff: 15:29 IST on expiry day -> Not expired
    before_cutoff = datetime(target_date.year, target_date.month, target_date.day, 15, 29, 0, tzinfo=IST)
    assert contract_expired("NFO", target_exp_str, current_time=before_cutoff) is False
    with patch("market_calendar.now_ist", return_value=before_cutoff):
        active_expiries = scrip_master.get_expiries("NIFTY", "future")
        assert active_expiries[0]["expiry"] == target_exp_str

    # After cutoff: 15:31 IST on expiry day -> Expired!
    after_cutoff = datetime(target_date.year, target_date.month, target_date.day, 15, 31, 0, tzinfo=IST)
    assert contract_expired("NFO", target_exp_str, current_time=after_cutoff) is True
    with patch("market_calendar.now_ist", return_value=after_cutoff):
        active_expiries_after = scrip_master.get_expiries("NIFTY", "future")
        # The expired contract must roll off; nearest expiry is now the NEXT contract
        if len(expiries_raw) > 1:
            assert active_expiries_after[0]["expiry"] == expiries_raw[1]["expiry"]
        else:
            assert target_exp_str not in [e["expiry"] for e in active_expiries_after]

    # Test MCX Expiry: GOLD cutoff is 23:30 IST
    mcx_expiries = scrip_master.get_expiries("GOLD", "future")
    assert len(mcx_expiries) > 0, "GOLD future expiries must be available in scrip master"
    gold_target_str = mcx_expiries[0]["expiry"]
    gold_target_date = datetime.strptime(gold_target_str, "%d%b%Y").date()

    # MCX before cutoff: 23:29 IST -> Not expired
    gold_before = datetime(gold_target_date.year, gold_target_date.month, gold_target_date.day, 23, 29, 0, tzinfo=IST)
    assert contract_expired("MCX", gold_target_str, current_time=gold_before) is False

    # MCX after cutoff: 23:31 IST -> Expired
    gold_after = datetime(gold_target_date.year, gold_target_date.month, gold_target_date.day, 23, 31, 0, tzinfo=IST)
    assert contract_expired("MCX", gold_target_str, current_time=gold_after) is True


# ---------------------------------------------------------------------------
# 2. Market closed rejection ("Market closed for <exchange>")
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_02_market_order_rejected_when_exchange_closed():
    """Market orders must be rejected with 400 'Market closed for <exchange>' outside session."""
    db = get_db()
    user_id = "mcx_test_user_closed"
    await db.users.insert_one({
        "user_id": user_id,
        "name": "Trader Closed Hours",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["future"],
        "allowed_instrument_types": ["INDEX"],
        "balance": 1000000.0,
        "available_balance": 1000000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
    })

    user_token = create_access_token(user_id=user_id, role="user")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    # Mock Sunday (Market closed)
    sunday_dt = datetime(2026, 9, 27, 11, 0, 0, tzinfo=IST)
    with patch("market_calendar.now_ist", return_value=sunday_dt):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/user/trade/future",
                json={"instrument": "NIFTY", "action": "BUY", "lots": 1},
                headers=user_headers,
            )
            assert res.status_code == 400
            assert "Market closed for" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 3. User without MCX permission gets 403 Forbidden
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_03_user_without_mcx_permission_gets_403():
    """User with allowed_instrument_types=['INDEX'] attempting MCX trade must receive 403."""
    db = get_db()
    user_id = "mcx_test_user_no_mcx"
    await db.users.insert_one({
        "user_id": user_id,
        "name": "Index Only User",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["future"],
        "allowed_instrument_types": ["INDEX"],  # No MCX!
        "balance": 1000000.0,
        "available_balance": 1000000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
    })

    user_token = create_access_token(user_id=user_id, role="user")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    with patch("market_calendar.now_ist", return_value=MOCK_WEDNESDAY_OPEN):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/user/trade/future",
                json={"instrument": "GOLD", "action": "BUY", "lots": 1},
                headers=user_headers,
            )
            assert res.status_code == 403
            assert "instrument type 'MCX' is not permitted" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Unconfigured MCX margin rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_04_unconfigured_mcx_margin_rejected():
    """MCX future with no margin configured by admin must be rejected with exact 400 message."""
    db = get_db()
    user_id = "mcx_test_user_margin"
    await db.users.insert_one({
        "user_id": user_id,
        "name": "MCX Trader",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["future"],
        "allowed_instrument_types": ["INDEX", "MCX"],
        "balance": 1000000.0,
        "available_balance": 1000000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
    })

    # Ensure no margin document exists for GOLD in MongoDB
    await db.instrument_margins.delete_many({"symbol": "GOLD", "segment": "future"})

    user_token = create_access_token(user_id=user_id, role="user")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    with patch("market_calendar.now_ist", return_value=MOCK_WEDNESDAY_OPEN):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=72000.0):
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post(
                    "/user/trade/future",
                    json={"instrument": "GOLD", "action": "BUY", "lots": 1},
                    headers=user_headers,
                )
                assert res.status_code == 400
                assert "Margin not configured for GOLD, admin must set it" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 5. GOLD 1 lot ₹100 move = ₹10,000 P&L
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_05_gold_one_lot_hundred_rupee_move_equals_ten_thousand_pnl():
    """Verify that GOLD (multiplier 100) generates (exit - entry) * lots * 100 P&L."""
    db = get_db()
    user_id = "mcx_test_user_gold_pnl"
    initial_balance = 500000.0

    await db.users.insert_one({
        "user_id": user_id,
        "name": "Gold Trader",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["future"],
        "allowed_instrument_types": ["INDEX", "MCX"],
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
    })

    # Admin sets margin for GOLD: ₹50,000 per lot
    margin_per_lot = 50000.0
    await db.instrument_margins.update_one(
        {"symbol": "GOLD", "segment": "future"},
        {"$set": {"symbol": "GOLD", "segment": "future", "margin_required": margin_per_lot}},
        upsert=True,
    )

    user_token = create_access_token(user_id=user_id, role="user")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    entry_price = 72000.0
    exit_price = 72100.0  # +₹100 move

    with patch("market_calendar.now_ist", return_value=MOCK_WEDNESDAY_OPEN):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=entry_price):
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post(
                    "/user/trade/future",
                    json={"instrument": "GOLD", "action": "BUY", "lots": 1},
                    headers=user_headers,
                )
                assert res.status_code == 200, res.text
                trade = res.json()["trade"]
                trade_id = trade["trade_id"]
                assert trade["instrument_type"] == "MCX"
                assert trade["pnl_multiplier_per_lot"] == 100.0
                assert trade["pnl_qty"] == 100.0  # 1 lot * 100
                assert trade["margin_blocked_amount"] == margin_per_lot

                # Check balance locked correctly
                user_doc = await db.users.find_one({"user_id": user_id})
                assert user_doc["available_balance"] == initial_balance - margin_per_lot
                assert user_doc["margin_blocked"] == margin_per_lot

        # Close trade via _close_single_trade with +₹100 move
        trade_doc = await db.trades_future.find_one({"trade_id": trade_id})
        closed_trade = await _close_single_trade(
            segment="future",
            trade=trade_doc,
            exit_price=exit_price,
            closed_by=user_id,
        )

        expected_pnl = round((exit_price - entry_price) * 1 * 100, 2)  # 100 * 100 = ₹10,000.0
        assert closed_trade["pnl"] == 10000.0
        assert closed_trade["status"] == "CLOSED"

        # Check balance updated with released margin + ₹10,000 realized profit
        updated_user = await db.users.find_one({"user_id": user_id})
        assert updated_user["margin_blocked"] == 0.0
        assert updated_user["available_balance"] == initial_balance + 10000.0
        assert updated_user["realized_pnl"] == 10000.0


# ---------------------------------------------------------------------------
# 6. NIFTY behaviour unchanged
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_06_nifty_behavior_unchanged():
    """Verify NIFTY index future execution, default lot size, margin, and standard PnL calculation."""
    db = get_db()
    user_id = "mcx_test_user_nifty"
    initial_balance = 200000.0

    await db.users.insert_one({
        "user_id": user_id,
        "name": "Nifty Trader",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["future"],
        "allowed_instrument_types": ["INDEX"],
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
    })

    # Set custom margin for NIFTY
    await db.instrument_margins.update_one(
        {"symbol": "NIFTY", "segment": "future"},
        {"$set": {"symbol": "NIFTY", "segment": "future", "margin_required": 75000.0}},
        upsert=True,
    )

    user_token = create_access_token(user_id=user_id, role="user")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    entry_price = 24000.0
    exit_price = 24050.0  # +50 points

    with patch("market_calendar.now_ist", return_value=MOCK_WEDNESDAY_OPEN):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=entry_price):
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post(
                    "/user/trade/future",
                    json={"instrument": "NIFTY", "action": "BUY", "lots": 1},
                    headers=user_headers,
                )
                assert res.status_code == 200, res.text
                trade = res.json()["trade"]
                trade_id = trade["trade_id"]
                assert trade["instrument_type"] == "INDEX"
                lot_size = trade["lot_size"]
                assert trade["pnl_qty"] == float(lot_size)

        # Close trade via _close_single_trade
        trade_doc = await db.trades_future.find_one({"trade_id": trade_id})
        closed_trade = await _close_single_trade(
            segment="future",
            trade=trade_doc,
            exit_price=exit_price,
            closed_by=user_id,
        )

        expected_pnl = round((exit_price - entry_price) * lot_size, 2)
        assert closed_trade["pnl"] == expected_pnl
        assert closed_trade["status"] == "CLOSED"
