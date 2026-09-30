import pytest
from httpx import ASGITransport, AsyncClient
from main import app
from auth import create_access_token
from db import get_db

@pytest.mark.asyncio
async def test_balance_and_margin_admin_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_token = create_access_token(user_id="admin", role="admin")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        db = get_db()
        # Seed test user
        await db.users.delete_many({"user_id": "margin_user_1"})
        await db.users.insert_one({
            "user_id": "margin_user_1",
            "name": "Margin User",
            "password_hash": "dummy",
            "allowed_segments": ["option", "future", "cash"],
            "trade_limit": {"option": 10, "future": 5, "cash": 50000},
            "balance": 10000.0,
            "available_balance": 10000.0,
            "margin_blocked": 2000.0,
            "realized_pnl": 500.0,
            "auto_square_off_pct": 80.0
        })

        # 1. Test Balance Set
        # Reject if balance < margin_blocked
        res = await client.put("/admin/users/margin_user_1/balance/set", json={"balance": 1500.0}, headers=admin_headers)
        assert res.status_code == 400
        assert "below currently locked margin" in res.json()["detail"]

        # Set valid balance
        res = await client.put("/admin/users/margin_user_1/balance/set", json={"balance": 20000.0}, headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["balance"] == 20000.0
        assert data["available_balance"] == 20000.0 - 2000.0 + 500.0  # 18500.0

        # 2. Test Balance Add
        # Subtract too much
        res = await client.put("/admin/users/margin_user_1/balance/add", json={"amount": -25000.0}, headers=admin_headers)
        assert res.status_code == 400

        # Add positive amount
        res = await client.put("/admin/users/margin_user_1/balance/add", json={"amount": 5000.0}, headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["balance"] == 25000.0
        assert data["available_balance"] == 18500.0 + 5000.0

        # Subtract valid amount
        res = await client.put("/admin/users/margin_user_1/balance/add", json={"amount": -3000.0}, headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["balance"] == 22000.0
        assert data["available_balance"] == 23500.0 - 3000.0

        # 3. Test Auto Square-off Threshold Update
        res = await client.put("/admin/users/margin_user_1/auto-square-off-threshold", json={"threshold_pct": 75.0}, headers=admin_headers)
        assert res.status_code == 200
        assert res.json()["auto_square_off_pct"] == 75.0

        # 4. Test Instrument Margin Setting & Listing
        res = await client.put("/admin/instruments/NIFTY/future/margin", json={"margin_required": 65000.0}, headers=admin_headers)
        assert res.status_code == 200
        assert res.json()["symbol"] == "NIFTY"
        assert res.json()["segment"] == "future"
        assert res.json()["margin_required"] == 65000.0

        res = await client.get("/admin/instruments/margins", headers=admin_headers)
        assert res.status_code == 200
        assert any(item["symbol"] == "NIFTY" and item["segment"] == "future" and item["margin_required"] == 65000.0 for item in res.json().get("margins", []))

@pytest.mark.asyncio
async def test_user_trade_execution_margin_flow():
    from unittest.mock import patch
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        db = get_db()
        await db.users.delete_many({"user_id": "margin_trader_test"})
        await db.trades_future.delete_many({"user_id": "margin_trader_test"})
        await db.instrument_margins.update_one(
            {"symbol": "NIFTY", "segment": "future"},
            {"$set": {"symbol": "NIFTY", "segment": "future", "margin_required": 25000.0}},
            upsert=True
        )

        await db.users.insert_one({
            "user_id": "margin_trader_test",
            "name": "Margin Trader",
            "password_hash": "dummy",
            "allowed_segments": ["future"],
            "trade_limit": {"option": 5, "future": 5, "cash": 50000},
            "trades_used": {"option": 0, "future": 0, "cash": 0},
            "balance": 40000.0,
            "available_balance": 40000.0,
            "margin_blocked": 0.0,
            "realized_pnl": 0.0,
            "is_active": True
        })

        user_token = create_access_token(user_id="margin_trader_test", role="user")
        user_headers = {"Authorization": f"Bearer {user_token}"}

        # 1. Reject trade when required margin > available balance
        payload_fail = {
            "instrument": "NIFTY",
            "action": "BUY",
            "lots": 2, # Requires 2 * 25000 = 50000 > 40000
            "expiry": "28MAR2026",
        }
        with patch("routers.user_routes.angel_client.get_ltp", return_value=22000.0):
            res_fail = await client.post("/user/trade/future", json=payload_fail, headers=user_headers)
        assert res_fail.status_code == 400
        assert "Insufficient margin" in res_fail.json()["detail"]

        # Verify trade count was not incremented
        user_doc = await db.users.find_one({"user_id": "margin_trader_test"})
        assert user_doc["trades_used"]["future"] == 0
        assert user_doc["available_balance"] == 40000.0
        assert user_doc["margin_blocked"] == 0.0

        # 2. Succeed trade when required margin <= available balance
        payload_ok = {
            "instrument": "NIFTY",
            "action": "BUY",
            "lots": 1, # Requires 25000 <= 40000
            "expiry": "28MAR2026",
        }
        with patch("routers.user_routes.angel_client.get_ltp", return_value=22000.0):
            res_ok = await client.post("/user/trade/future", json=payload_ok, headers=user_headers)
            assert res_ok.status_code == 200
            trade_data = res_ok.json()["trade"]
            assert trade_data["status"] == "OPEN"
            assert trade_data["margin_blocked_amount"] == 25000.0

            # Verify balance updates
            user_doc_ok = await db.users.find_one({"user_id": "margin_trader_test"})
            assert user_doc_ok["trades_used"]["future"] == 1
            assert user_doc_ok["available_balance"] == 15000.0
            assert user_doc_ok["margin_blocked"] == 25000.0

            # 3. Close the trade -> Margin released & Realized PnL applied
            trade_id = trade_data["trade_id"]
            with patch("routers.user_routes.angel_client.get_ltp", return_value=22050.0):
                res_close = await client.post(f"/user/trade/future/{trade_id}/close", headers=user_headers)
                assert res_close.status_code == 200
                closed_trade = res_close.json()["trade"]
                assert closed_trade["status"] == "CLOSED"
                pnl = closed_trade["pnl"]
                assert pnl > 0

                # User available_balance should be: old_available (15000) + released_margin (25000) + pnl = 40000 + pnl
                user_doc_after = await db.users.find_one({"user_id": "margin_trader_test"})
                assert user_doc_after["margin_blocked"] == 0.0
                assert user_doc_after["available_balance"] == 40000.0 + pnl
                assert user_doc_after["realized_pnl"] == pnl
                assert user_doc_after["balance"] == 40000.0

@pytest.mark.asyncio
async def test_mtm_engine_and_auto_square_off():
    from unittest.mock import patch
    from mtm_engine import run_mtm_cycle
    from datetime import datetime, timezone

    db = get_db()
    user_id = "auto_sq_user"
    await db.users.delete_many({"user_id": user_id})
    await db.trades_future.delete_many({"user_id": user_id})
    await db.audit_logs.delete_many({"target_user_id": user_id})

    # User with 10,000 balance, auto square-off threshold at 80% (loss >= 8,000 => equity <= 2,000)
    now = datetime.now(timezone.utc)
    await db.users.insert_one({
        "user_id": user_id,
        "name": "Auto Square-off Tester",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["future"],
        "trade_limit": {"option": 5, "future": 5, "cash": 50000},
        "trades_used": {"option": 0, "future": 1, "cash": 0},
        "balance": 10000.0,
        "available_balance": 5000.0,
        "margin_blocked": 5000.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "equity": 10000.0,
        "loss_pct": 0.0,
        "auto_square_off_pct": 80.0,
        "last_auto_square_off_at": None,
    })

    # Insert open future trade: bought 100 qty at 22000.0 (margin blocked 5,000)
    trade_doc = {
        "trade_id": "TRD-FUT-AUTOSQ-1",
        "user_id": user_id,
        "segment": "future",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26MARFUT",
        "exchange": "NFO",
        "symboltoken": "99999",
        "action": "BUY",
        "qty": 100,
        "entry_price": 22000.0,
        "entry_time": now,
        "exit_price": None,
        "exit_time": None,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 5000.0,
        "created_at": now,
        "updated_at": now,
    }
    await db.trades_future.insert_one(trade_doc)

    # 1. Normal MTM Cycle: price dropped slightly to 21990.0 (-10 * 100 = -1,000 loss => loss_pct = 10%)
    with patch("mtm_engine.angel_client.get_ltp", return_value=21990.0):
        await run_mtm_cycle()

    user_check_1 = await db.users.find_one({"user_id": user_id})
    assert user_check_1["unrealized_pnl"] == -1000.0
    assert user_check_1["equity"] == 9000.0
    assert user_check_1["loss_pct"] == 10.0

    # Trade should still be OPEN
    trade_check_1 = await db.trades_future.find_one({"trade_id": "TRD-FUT-AUTOSQ-1"})
    assert trade_check_1["status"] == "OPEN"

    # 2. Severe loss MTM Cycle: price crashes to 21915.0 (-85 * 100 = -8,500 loss => loss_pct = 85% >= 80%)
    with patch("mtm_engine.angel_client.get_ltp", return_value=21915.0):
        await run_mtm_cycle()

    # Trade should now be automatically CLOSED
    trade_check_2 = await db.trades_future.find_one({"trade_id": "TRD-FUT-AUTOSQ-1"})
    assert trade_check_2["status"] == "CLOSED"
    assert trade_check_2["exit_price"] == 21915.0
    assert trade_check_2["pnl"] == -8500.0
    assert trade_check_2["closed_by"] == "SYSTEM_AUTO_SQUARE_OFF"

    # User balance should have margin released (5000) and realized pnl applied (-8500)
    user_check_2 = await db.users.find_one({"user_id": user_id})
    assert user_check_2["margin_blocked"] == 0.0
    assert user_check_2["realized_pnl"] == -8500.0
    assert user_check_2["available_balance"] == 5000.0 + 5000.0 - 8500.0  # 1500.0
    assert user_check_2["last_auto_square_off_at"] is not None

    # Audit log check
    audit_log = await db.audit_logs.find_one({"target_user_id": user_id, "action": "AUTO_SQUARE_OFF"})
    assert audit_log is not None
    assert audit_log["admin_id"] == "SYSTEM"
    tc = audit_log["details"]["trades_closed"]
    assert tc == 1 or tc == {"option": 0, "future": 1, "cash": 0} or (isinstance(tc, dict) and sum(tc.values()) == 1)

@pytest.mark.asyncio
async def test_admin_list_users_risk_level_and_filtering():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_token = create_access_token(user_id="admin", role="admin")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        db = get_db()

        # Seed users with different loss_pct
        await db.users.delete_many({"user_id": {"$in": ["user_safe", "user_warn", "user_crit"]}})

        await db.users.insert_many([
            {
                "user_id": "user_safe",
                "name": "Safe User",
                "password_hash": "dummy",
                "is_active": True,
                "allowed_segments": ["future"],
                "trade_limit": {"option": 5, "future": 5, "cash": 50000},
                "balance": 10000.0,
                "available_balance": 10000.0,
                "margin_blocked": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "equity": 10000.0,
                "loss_pct": 20.0,
            },
            {
                "user_id": "user_warn",
                "name": "Warning User",
                "password_hash": "dummy",
                "is_active": True,
                "allowed_segments": ["future"],
                "trade_limit": {"option": 5, "future": 5, "cash": 50000},
                "balance": 10000.0,
                "available_balance": 3500.0,
                "margin_blocked": 3000.0,
                "realized_pnl": -3500.0,
                "unrealized_pnl": -3000.0,
                "equity": 3500.0,
                "loss_pct": 65.0,
            },
            {
                "user_id": "user_crit",
                "name": "Critical User",
                "password_hash": "dummy",
                "is_active": True,
                "allowed_segments": ["future"],
                "trade_limit": {"option": 5, "future": 5, "cash": 50000},
                "balance": 10000.0,
                "available_balance": 10000.0,
                "margin_blocked": 1000.0,
                "realized_pnl": -5000.0,
                "unrealized_pnl": -3500.0,
                "equity": 1500.0,
                "loss_pct": 85.0,
            }
        ])

        # 1. Unfiltered list
        res = await client.get("/admin/users", headers=admin_headers)
        assert res.status_code == 200
        users_by_id = {u["user_id"]: u for u in res.json() if u["user_id"] in ("user_safe", "user_warn", "user_crit")}
        assert users_by_id["user_safe"]["risk_level"] == "normal"
        assert users_by_id["user_warn"]["risk_level"] == "warning"
        assert users_by_id["user_crit"]["risk_level"] == "critical"

        # 2. Filter with ?low_balance_threshold=70
        res_filter_70 = await client.get("/admin/users?low_balance_threshold=70", headers=admin_headers)
        assert res_filter_70.status_code == 200
        filtered_ids = [u["user_id"] for u in res_filter_70.json()]
        assert "user_crit" in filtered_ids
        assert "user_warn" not in filtered_ids
        assert "user_safe" not in filtered_ids

        # 3. Filter with ?low_balance_threshold=60
        res_filter_60 = await client.get("/admin/users?low_balance_threshold=60", headers=admin_headers)
        assert res_filter_60.status_code == 200
        filtered_ids_60 = [u["user_id"] for u in res_filter_60.json()]
        assert "user_crit" in filtered_ids_60
        assert "user_warn" in filtered_ids_60
        assert "user_safe" not in filtered_ids_60
