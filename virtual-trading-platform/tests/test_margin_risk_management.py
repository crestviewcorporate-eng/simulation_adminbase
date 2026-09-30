import asyncio
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient

from auth import create_access_token
from db import get_db
from main import app
from mtm_engine import run_mtm_cycle, _close_single_trade


@pytest.fixture(autouse=True)
async def setup_test_environment():
    db = get_db()
    # Clean up test collections
    test_user_prefix = "mrm_test_"
    await db.users.delete_many({"user_id": {"$regex": f"^{test_user_prefix}"}})
    for seg in ["option", "future", "cash"]:
        await db[f"trades_{seg}"].delete_many({"user_id": {"$regex": f"^{test_user_prefix}"}})
    await db.audit_logs.delete_many({"target_user_id": {"$regex": f"^{test_user_prefix}"}})

    # Seed cash test instruments
    await db.instruments.update_one(
        {"symbol": "RELIANCE", "segment": "cash"},
        {"$set": {"symbol": "RELIANCE", "segment": "cash", "exchange": "NSE", "tradingsymbol": "RELIANCE-EQ", "symboltoken": "2885", "lot_size": 1}},
        upsert=True,
    )
    await db.instruments.update_one(
        {"symbol": "TCS", "segment": "cash"},
        {"$set": {"symbol": "TCS", "segment": "cash", "exchange": "NSE", "tradingsymbol": "TCS-EQ", "symboltoken": "11536", "lot_size": 1}},
        upsert=True,
    )
    yield


# ---------------------------------------------------------------------------
# 1. Admin sets balance for a user -> user.balance & available_balance update
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_01_admin_sets_balance_for_user():
    db = get_db()
    user_id = "mrm_test_user_01"
    await db.users.insert_one({
        "user_id": user_id,
        "name": "User One",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option", "future", "cash"],
        "balance": 10000.0,
        "available_balance": 10000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "equity": 10000.0,
        "loss_pct": 0.0,
    })

    admin_token = create_access_token(user_id="admin", role="admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.put(f"/admin/users/{user_id}/balance/set", json={"balance": 50000.0}, headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["balance"] == 50000.0
        assert data["available_balance"] == 50000.0

        user_doc = await db.users.find_one({"user_id": user_id})
        assert user_doc["balance"] == 50000.0
        assert user_doc["available_balance"] == 50000.0


# ---------------------------------------------------------------------------
# 2. Admin sets balance below current margin_blocked -> rejected with 400
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_02_admin_sets_balance_below_margin_blocked_rejected():
    db = get_db()
    user_id = "mrm_test_user_02"
    await db.users.insert_one({
        "user_id": user_id,
        "name": "User Two",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option", "future", "cash"],
        "balance": 50000.0,
        "available_balance": 20000.0,
        "margin_blocked": 30000.0,
        "realized_pnl": 0.0,
    })

    admin_token = create_access_token(user_id="admin", role="admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.put(f"/admin/users/{user_id}/balance/set", json={"balance": 25000.0}, headers=admin_headers)
        assert res.status_code == 400
        assert "below currently locked margin" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 3. Place Option trade -> required_lock == LTP * qty, balance locked exactly
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_03_place_option_trade_locks_exact_amount():
    db = get_db()
    user_id = "mrm_test_user_03"
    await db.users.insert_one({
        "user_id": user_id,
        "name": "User Option Buyer",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option"],
        "balance": 50000.0,
        "available_balance": 50000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
    })

    user_token = create_access_token(user_id=user_id, role="user")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # LTP = 150.0, 1 lot = 65 qty => Required = 150.0 * 65 = 9,750.0
        with patch("routers.user_routes.angel_client.get_ltp", return_value=150.0):
            payload = {
                "instrument": "NIFTY",
                "expiry": "22SEP2026",
                "strike": 23300.0,
                "option_type": "CE",
                "action": "BUY",
                "lots": 1,
                "qty": 65,
            }
            res = await client.post("/user/trade/option", json=payload, headers=user_headers)
            assert res.status_code == 200
            trade = res.json()["trade"]
            assert trade["entry_price"] == 150.0
            assert trade["qty"] == 65
            assert trade["margin_blocked_amount"] == 9750.0

            user_doc = await db.users.find_one({"user_id": user_id})
            assert user_doc["available_balance"] == 50000.0 - 9750.0  # 40,250.0
            assert user_doc["margin_blocked"] == 9750.0


# ---------------------------------------------------------------------------
# 4. Place Cash trade -> required_lock == LTP * qty, balance locked exactly
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_04_place_cash_trade_locks_exact_amount():
    db = get_db()
    user_id = "mrm_test_user_04"
    await db.users.insert_one({
        "user_id": user_id,
        "name": "User Cash Buyer",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["cash"],
        "balance": 100000.0,
        "available_balance": 100000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
    })

    user_token = create_access_token(user_id=user_id, role="user")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # LTP = 2500.0, Qty = 10 => Required = 25,000.0
        with patch("routers.user_routes.angel_client.get_ltp", return_value=2500.0):
            payload = {
                "instrument": "RELIANCE",
                "action": "BUY",
                "qty": 10,
            }
            res = await client.post("/user/trade/cash", json=payload, headers=user_headers)
            assert res.status_code == 200
            trade = res.json()["trade"]
            assert trade["entry_price"] == 2500.0
            assert trade["qty"] == 10
            assert trade["margin_blocked_amount"] == 25000.0

            user_doc = await db.users.find_one({"user_id": user_id})
            assert user_doc["available_balance"] == 75000.0  # 100,000 - 25,000
            assert user_doc["margin_blocked"] == 25000.0


# ---------------------------------------------------------------------------
# 5. Shortfall Error on Option & Cash when available_balance < required_lock
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_05_insufficient_balance_for_option_and_cash_returns_400_shortfall():
    db = get_db()
    user_id = "mrm_test_user_05"
    await db.users.insert_one({
        "user_id": user_id,
        "name": "User Low Balance",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option", "cash"],
        "balance": 5000.0,
        "available_balance": 5000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
    })

    user_token = create_access_token(user_id=user_id, role="user")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Option shortfall: LTP = 100.0 * 65 qty = 6,500.0 > 5,000.0
        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0):
            opt_payload = {
                "instrument": "NIFTY",
                "expiry": "22SEP2026",
                "strike": 23300.0,
                "option_type": "CE",
                "action": "BUY",
                "lots": 1,
                "qty": 65,
            }
            res_opt = await client.post("/user/trade/option", json=opt_payload, headers=user_headers)
            assert res_opt.status_code == 400
            err_opt = res_opt.json()["detail"]
            assert "Insufficient margin" in err_opt
            assert "Required: ₹6,500.00" in err_opt
            assert "Available: ₹5,000.00" in err_opt
            assert "Shortfall: ₹1,500.00" in err_opt

        # 2. Cash shortfall: LTP = 3000.0 * 5 qty = 15,000.0 > 5,000.0
        with patch("routers.user_routes.angel_client.get_ltp", return_value=3000.0):
            cash_payload = {
                "instrument": "TCS",
                "action": "BUY",
                "qty": 5,
            }
            res_cash = await client.post("/user/trade/cash", json=cash_payload, headers=user_headers)
            assert res_cash.status_code == 400
            err_cash = res_cash.json()["detail"]
            assert "Insufficient margin" in err_cash
            assert "Required: ₹15,000.00" in err_cash
            assert "Available: ₹5,000.00" in err_cash
            assert "Shortfall: ₹10,000.00" in err_cash

        # Ensure user account was untouched
        user_doc = await db.users.find_one({"user_id": user_id})
        assert user_doc["available_balance"] == 5000.0
        assert user_doc["margin_blocked"] == 0.0


# ---------------------------------------------------------------------------
# 6. Close Option & Cash trades -> release margin & apply realized P&L
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_06_close_option_and_cash_trades_releases_margin_and_applies_pnl():
    db = get_db()
    user_id = "mrm_test_user_06"
    now = datetime.now(timezone.utc)
    await db.users.insert_one({
        "user_id": user_id,
        "name": "User Closer",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option", "cash"],
        "balance": 100000.0,
        "available_balance": 60000.0,
        "margin_blocked": 40000.0,
        "realized_pnl": 0.0,
    })

    # Option trade: locked 10,000. Entry = 100, qty = 100
    opt_trade_id = "TRD-OPT-TEST-06"
    await db.trades_option.insert_one({
        "trade_id": opt_trade_id,
        "user_id": user_id,
        "segment": "option",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26MAR22500CE",
        "exchange": "NFO",
        "symboltoken": "12345",
        "action": "BUY",
        "qty": 100,
        "entry_price": 100.0,
        "entry_time": now,
        "exit_price": None,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 10000.0,
        "created_at": now,
        "updated_at": now,
    })

    # Cash trade: locked 30,000. Entry = 300, qty = 100
    cash_trade_id = "TRD-CSH-TEST-06"
    await db.trades_cash.insert_one({
        "trade_id": cash_trade_id,
        "user_id": user_id,
        "segment": "cash",
        "instrument": "INFY",
        "tradingsymbol": "INFY-EQ",
        "exchange": "NSE",
        "symboltoken": "67890",
        "action": "BUY",
        "qty": 100,
        "entry_price": 300.0,
        "entry_time": now,
        "exit_price": None,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 30000.0,
        "created_at": now,
        "updated_at": now,
    })

    user_token = create_access_token(user_id=user_id, role="user")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Close Option at 150.0 -> PnL = (150 - 100) * 100 = +5,000.0
        with patch("routers.user_routes.angel_client.get_ltp", return_value=150.0):
            res_opt = await client.post(f"/user/trade/option/{opt_trade_id}/close", headers=user_headers)
            assert res_opt.status_code == 200
            assert res_opt.json()["trade"]["pnl"] == 5000.0

            user_doc = await db.users.find_one({"user_id": user_id})
            # margin_blocked reduced by 10,000 (from 40,000 to 30,000)
            assert user_doc["margin_blocked"] == 30000.0
            assert user_doc["realized_pnl"] == 5000.0
            # available_balance increased by 10,000 + 5,000 = 15,000 (from 60,000 to 75,000)
            assert user_doc["available_balance"] == 75000.0

        # 2. Close Cash at 260.0 -> PnL = (260 - 300) * 100 = -4,000.0
        with patch("routers.user_routes.angel_client.get_ltp", return_value=260.0):
            res_cash = await client.post(f"/user/trade/cash/{cash_trade_id}/close", headers=user_headers)
            assert res_cash.status_code == 200
            assert res_cash.json()["trade"]["pnl"] == -4000.0

            user_doc2 = await db.users.find_one({"user_id": user_id})
            # margin_blocked fully released to 0
            assert user_doc2["margin_blocked"] == 0.0
            # Net realized PnL = 5000 - 4000 = 1000.0
            assert user_doc2["realized_pnl"] == 1000.0
            # available_balance = 75000 + 30000 - 4000 = 101,000.0
            assert user_doc2["available_balance"] == 101000.0


# ---------------------------------------------------------------------------
# 7. MTM Engine sums Option + Future + Cash combined & Auto Square Off all 3
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_07_mtm_engine_sums_all_segments_and_auto_squares_off_all_open_positions():
    db = get_db()
    user_id = "mrm_test_user_07"
    now = datetime.now(timezone.utc)

    # Balance 50,000
    await db.users.insert_one({
        "user_id": user_id,
        "name": "Multi Segment Trader",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option", "future", "cash"],
        "balance": 50000.0,
        "available_balance": 10000.0,
        "margin_blocked": 40000.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "equity": 50000.0,
        "loss_pct": 0.0,
        "auto_square_off_pct": 80.0,
        "last_auto_square_off_at": None,
    })

    # 1. Open Option Trade: entry 100, qty 100, margin 10,000
    opt_trade_id = "TRD-OPT-MULTI-07"
    await db.trades_option.insert_one({
        "trade_id": opt_trade_id,
        "user_id": user_id,
        "segment": "option",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26MAR22500CE",
        "exchange": "NFO",
        "symboltoken": "101",
        "action": "BUY",
        "qty": 100,
        "entry_price": 100.0,
        "entry_time": now,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 10000.0,
        "created_at": now,
        "updated_at": now,
    })

    # 2. Open Future Trade: entry 22000, qty 50, margin 20,000
    fut_trade_id = "TRD-FUT-MULTI-07"
    await db.trades_future.insert_one({
        "trade_id": fut_trade_id,
        "user_id": user_id,
        "segment": "future",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26MARFUT",
        "exchange": "NFO",
        "symboltoken": "102",
        "action": "BUY",
        "qty": 50,
        "entry_price": 22000.0,
        "entry_time": now,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 20000.0,
        "created_at": now,
        "updated_at": now,
    })

    # 3. Open Cash Trade: entry 1000, qty 10, margin 10,000
    csh_trade_id = "TRD-CSH-MULTI-07"
    await db.trades_cash.insert_one({
        "trade_id": csh_trade_id,
        "user_id": user_id,
        "segment": "cash",
        "instrument": "TCS",
        "tradingsymbol": "TCS-EQ",
        "exchange": "NSE",
        "symboltoken": "103",
        "action": "BUY",
        "qty": 10,
        "entry_price": 1000.0,
        "entry_time": now,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 10000.0,
        "created_at": now,
        "updated_at": now,
    })

    # Price movements:
    # Option: 100 -> 20 => PnL = (20 - 100) * 100 = -8,000
    # Future: 22000 -> 21360 => PnL = (21360 - 22000) * 50 = -32,000
    # Cash: 1000 -> 800 => PnL = (800 - 1000) * 10 = -2,000
    # Combined Unrealized PnL = -8000 + -32000 + -2000 = -42,000
    # Equity = 50,000 - 42,000 = 8,000
    # Loss % = 42,000 / 50,000 = 84% >= 80% threshold -> Triggers Auto Square Off!

    def mock_ltp(exchange, tradingsymbol, symboltoken):
        if "CE" in tradingsymbol:
            return 20.0
        elif "FUT" in tradingsymbol:
            return 21360.0
        else:
            return 800.0

    with patch("mtm_engine.angel_client.get_ltp", side_effect=mock_ltp):
        await run_mtm_cycle()

    # Confirm ALL 3 trades across ALL 3 segments were closed
    opt_doc = await db.trades_option.find_one({"trade_id": opt_trade_id})
    fut_doc = await db.trades_future.find_one({"trade_id": fut_trade_id})
    csh_doc = await db.trades_cash.find_one({"trade_id": csh_trade_id})

    assert opt_doc["status"] == "CLOSED"
    assert opt_doc["closed_by"] == "SYSTEM_AUTO_SQUARE_OFF"
    assert opt_doc["pnl"] == -8000.0

    assert fut_doc["status"] == "CLOSED"
    assert fut_doc["closed_by"] == "SYSTEM_AUTO_SQUARE_OFF"
    assert fut_doc["pnl"] == -32000.0

    assert csh_doc["status"] == "CLOSED"
    assert csh_doc["closed_by"] == "SYSTEM_AUTO_SQUARE_OFF"
    assert csh_doc["pnl"] == -2000.0

    # User state assertions
    user_doc = await db.users.find_one({"user_id": user_id})
    assert user_doc["margin_blocked"] == 0.0
    assert user_doc["realized_pnl"] == -42000.0
    assert user_doc["available_balance"] == 8000.0
    assert user_doc["last_auto_square_off_at"] is not None

    # Audit log verification with per-segment breakdown
    audit_entry = await db.audit_logs.find_one({"target_user_id": user_id, "action": "AUTO_SQUARE_OFF"})
    assert audit_entry is not None
    assert audit_entry["details"]["trades_closed"] == {"option": 1, "future": 1, "cash": 1}
    assert audit_entry["details"]["loss_pct"] == 84.0


# ---------------------------------------------------------------------------
# 8. Concurrent Close Race Test (Atomic find_one_and_update safety)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_08_concurrent_trade_close_race_condition_safe():
    db = get_db()
    user_id = "mrm_test_user_08_race"
    now = datetime.now(timezone.utc)
    trade_id = "TRD-FUT-RACE-08"

    await db.users.insert_one({
        "user_id": user_id,
        "name": "Race User",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["future"],
        "balance": 100000.0,
        "available_balance": 50000.0,
        "margin_blocked": 50000.0,
        "realized_pnl": 0.0,
    })

    await db.trades_future.insert_one({
        "trade_id": trade_id,
        "user_id": user_id,
        "segment": "future",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26MARFUT",
        "exchange": "NFO",
        "symboltoken": "999",
        "action": "BUY",
        "qty": 50,
        "entry_price": 22000.0,
        "entry_time": now,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 50000.0,
        "created_at": now,
        "updated_at": now,
    })

    trade_doc = await db.trades_future.find_one({"trade_id": trade_id})

    # Run two closes simultaneously (e.g. manual request + auto-close)
    task1 = _close_single_trade(
        segment="future",
        trade=trade_doc,
        exit_price=22100.0,
        closed_by="MANUAL",
    )
    task2 = _close_single_trade(
        segment="future",
        trade=trade_doc,
        exit_price=22100.0,
        closed_by="SYSTEM_AUTO_SQUARE_OFF",
    )

    result1, result2 = await asyncio.gather(task1, task2)

    # Exactly one succeeded and one exited silently with None
    results = [result1, result2]
    successful_closes = [r for r in results if r is not None]
    assert len(successful_closes) == 1

    # Check database state: exactly ONE margin release and ONE P&L application
    user_doc = await db.users.find_one({"user_id": user_id})
    assert user_doc["margin_blocked"] == 0.0
    assert user_doc["realized_pnl"] == 5000.0  # (22100 - 22000) * 50 = +5,000
    assert user_doc["available_balance"] == 50000.0 + 50000.0 + 5000.0  # 105,000.0

    trade_final = await db.trades_future.find_one({"trade_id": trade_id})
    assert trade_final["status"] == "CLOSED"
    assert trade_final["pnl"] == 5000.0
    assert trade_final["exit_price"] == 22100.0


# ---------------------------------------------------------------------------
# 9. GET /admin/users?low_balance_threshold=70 returns only users at/above threshold
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_09_admin_filter_users_by_low_balance_threshold():
    db = get_db()
    admin_token = create_access_token(user_id="admin", role="admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    transport = ASGITransport(app=app)

    await db.users.insert_many([
        {
            "user_id": "mrm_test_user_09_low",
            "name": "Low Loss",
            "password_hash": "dummy",
            "is_active": True,
            "allowed_segments": ["option"],
            "balance": 10000.0,
            "available_balance": 10000.0,
            "margin_blocked": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "equity": 8000.0,
            "loss_pct": 20.0,
        },
        {
            "user_id": "mrm_test_user_09_high",
            "name": "High Loss",
            "password_hash": "dummy",
            "is_active": True,
            "allowed_segments": ["option"],
            "balance": 10000.0,
            "available_balance": 2500.0,
            "margin_blocked": 0.0,
            "realized_pnl": -7500.0,
            "unrealized_pnl": 0.0,
            "equity": 2500.0,
            "loss_pct": 75.0,
        },
    ])

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/admin/users?low_balance_threshold=70", headers=admin_headers)
        assert res.status_code == 200
        user_ids = [u["user_id"] for u in res.json()]
        assert "mrm_test_user_09_high" in user_ids
        assert "mrm_test_user_09_low" not in user_ids
