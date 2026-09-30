import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from main import app
from db import get_db
from auth import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Setup / Teardown Helper
# ---------------------------------------------------------------------------
async def reset_test_db():
    db = get_db()
    test_user_ids = ["trader_alpha", "trader_beta", "trader_concurrent", "trader_pnl", "trader_force", "trader_sec"]
    await db.users.delete_many({"user_id": {"$in": test_user_ids}})
    await db.admins.delete_many({"username": "super_admin"})
    await db.audit_logs.delete_many({"admin_id": "super_admin"})
    for seg in ["option", "future", "cash"]:
        await db[f"trades_{seg}"].delete_many({"user_id": {"$in": test_user_ids}})

    # Seed test admin
    await db.admins.insert_one({
        "username": "super_admin",
        "password_hash": hash_password("AdminSecure@123"),
        "role": "admin",
        "created_at": datetime.now(timezone.utc),
    })


def get_admin_headers():
    token = create_access_token(user_id="super_admin", role="admin")
    return {"Authorization": f"Bearer {token}"}


def get_user_headers(user_id="trader_alpha"):
    token = create_access_token(user_id=user_id, role="user")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 12 Comprehensive Test Cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_01_admin_creates_user_successfully():
    """1. Admin creates a user successfully."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "user_id": "trader_alpha",
            "password": "Password@123",
            "name": "Alpha Trader",
            "allowed_segments": ["option", "future"],
            "trade_limit": {"option": 5, "future": 2, "cash": 0}, "balance": 500000.0, "available_balance": 500000.0,
        }
        res = await client.post("/admin/users", json=payload, headers=admin_headers)
        assert res.status_code == 201
        data = res.json()
        assert data["user_id"] == "trader_alpha"
        assert data["name"] == "Alpha Trader"
        assert data["allowed_segments"] == ["option", "future"]
        assert data["trade_limit"]["option"] == 5


@pytest.mark.asyncio
async def test_02_duplicate_user_id_returns_409():
    """2. Duplicate user_id creation returns 409."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "user_id": "trader_alpha",
            "password": "Password@123",
            "name": "Alpha Trader",
            "allowed_segments": ["option"],
            "trade_limit": {"option": 10, "future": 0, "cash": 0}, "balance": 500000.0, "available_balance": 500000.0,
        }
        # First creation succeeds
        res1 = await client.post("/admin/users", json=payload, headers=admin_headers)
        assert res1.status_code == 201

        # Second creation with identical user_id fails with 409 Conflict
        res2 = await client.post("/admin/users", json=payload, headers=admin_headers)
        assert res2.status_code == 409
        assert "already exists" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_03_disallowed_segment_returns_403():
    """3. User trading in a disallowed segment returns 403."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    user_headers = get_user_headers("trader_alpha")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create user with ONLY 'option' allowed
        await client.post(
            "/admin/users",
            json={
                "user_id": "trader_alpha",
                "password": "Password@123",
                "name": "Alpha Trader",
                "allowed_segments": ["option"],
                "trade_limit": {"option": 10, "future": 5, "cash": 50000}, "balance": 500000.0, "available_balance": 500000.0,
            },
            headers=admin_headers,
        )

        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0):
            # Attempting future trade -> 403 Forbidden
            fut_payload = {"instrument": "BANKNIFTY", "expiry": "28MAR2026", "action": "BUY", "qty": 15}
            res_fut = await client.post("/user/trade/future", json=fut_payload, headers=user_headers)
            assert res_fut.status_code == 403
            assert "not permitted" in res_fut.json()["detail"]

            # Attempting cash trade -> 403 Forbidden
            cash_payload = {"instrument": "NIFTY", "action": "BUY", "qty": 10}
            res_cash = await client.post("/user/trade/cash", json=cash_payload, headers=user_headers)
            assert res_cash.status_code == 403


@pytest.mark.asyncio
async def test_04_trade_limit_exhausted_blocks_trade_no_db_insert():
    """4. Trade limit exhausted blocks a new trade with no DB insert."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    user_headers = get_user_headers("trader_alpha")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create user with trade_limit = 1 for option
        await client.post(
            "/admin/users",
            json={
                "user_id": "trader_alpha",
                "password": "Password@123",
                "name": "Alpha Trader",
                "allowed_segments": ["option"],
                "trade_limit": {"option": 1, "future": 0, "cash": 0}, "balance": 500000.0, "available_balance": 500000.0,
                "balance": 500000.0,
                "available_balance": 500000.0,
            },
            headers=admin_headers,
        )

        opt_payload = {
            "instrument": "NIFTY",
            "expiry": "28MAR2026",
            "strike": 22500.0,
            "option_type": "CE",
            "action": "BUY",
            "qty": 25,
        }

        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0), \
             patch("market_calendar.is_market_open", return_value=True):
            # 1st trade succeeds
            res1 = await client.post("/user/trade/option", json=opt_payload, headers=user_headers)
            assert res1.status_code == 200

            # 2nd trade blocked
            res2 = await client.post("/user/trade/option", json=opt_payload, headers=user_headers)
            assert res2.status_code == 400
            assert "limit exhausted" in res2.json()["detail"].lower()

            # Verify DB has exactly 1 trade
            db = get_db()
            count = await db.trades_option.count_documents({"user_id": "trader_alpha"})
            assert count == 1


@pytest.mark.asyncio
async def test_05_concurrent_trades_single_slot_race_condition():
    """5. Two concurrent trade requests when only 1 slot remains → exactly one succeeds."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    token = create_access_token(user_id="trader_concurrent", role="user")
    headers = {"Authorization": f"Bearer {token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create user with limit 1
        await client.post(
            "/admin/users",
            json={
                "user_id": "trader_concurrent",
                "password": "Password@123",
                "name": "Concurrent Trader",
                "allowed_segments": ["option"],
                "trade_limit": {"option": 1, "future": 0, "cash": 0}, "balance": 500000.0, "available_balance": 500000.0,
                "balance": 500000.0,
                "available_balance": 500000.0,
            },
            headers=admin_headers,
        )

        opt_payload = {
            "instrument": "NIFTY",
            "expiry": "28MAR2026",
            "strike": 22500.0,
            "option_type": "CE",
            "action": "BUY",
            "qty": 25,
        }

        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0), \
             patch("market_calendar.is_market_open", return_value=True):
            # Fire 2 concurrent requests
            res1, res2 = await asyncio.gather(
                client.post("/user/trade/option", json=opt_payload, headers=headers),
                client.post("/user/trade/option", json=opt_payload, headers=headers),
            )

            status_codes = sorted([res1.status_code, res2.status_code])
            # Exactly one 200 (Success) and one 400 (Limit exhausted)
            assert status_codes == [200, 400]

            # Verify total trades in MongoDB is exactly 1
            db = get_db()
            trade_count = await db.trades_option.count_documents({"user_id": "trader_concurrent"})
            assert trade_count == 1


@pytest.mark.asyncio
async def test_06_admin_limit_increase_allows_trading_again():
    """6. Admin limit-increase raises the limit; user can trade again after."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    user_headers = get_user_headers("trader_alpha")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User initially with limit = 1
        await client.post(
            "/admin/users",
            json={
                "user_id": "trader_alpha",
                "password": "Password@123",
                "name": "Alpha Trader",
                "allowed_segments": ["option"],
                "trade_limit": {"option": 1, "future": 0, "cash": 0}, "balance": 500000.0, "available_balance": 500000.0,
                "balance": 500000.0,
                "available_balance": 500000.0,
            },
            headers=admin_headers,
        )

        opt_payload = {
            "instrument": "NIFTY",
            "expiry": "28MAR2026",
            "strike": 22500.0,
            "option_type": "CE",
            "action": "BUY",
            "qty": 25,
        }

        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0), \
             patch("market_calendar.is_market_open", return_value=True):
            # Exhaust limit
            res_trade1 = await client.post("/user/trade/option", json=opt_payload, headers=user_headers)
            assert res_trade1.status_code == 200

            # Attempt trade -> blocked
            res_blocked = await client.post("/user/trade/option", json=opt_payload, headers=user_headers)
            assert res_blocked.status_code == 400

            # Admin increases limit to 2
            res_inc = await client.post(
                "/admin/users/trader_alpha/limit-increase",
                json={"segment": "option", "new_limit": 2},
                headers=admin_headers,
            )
            assert res_inc.status_code == 200
            assert res_inc.json()["new_limit"] == 2

            # User trades again -> succeeds
            res_trade2 = await client.post("/user/trade/option", json=opt_payload, headers=user_headers)
            assert res_trade2.status_code == 200


@pytest.mark.asyncio
async def test_07_admin_limit_revoke_distinct_audited_action():
    """7. Admin limit-revoke lowers the limit and is a distinct audited action from increase."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create user
        await client.post(
            "/admin/users",
            json={
                "user_id": "trader_alpha",
                "password": "Password@123",
                "name": "Alpha Trader",
                "allowed_segments": ["option"],
                "trade_limit": {"option": 10, "future": 0, "cash": 0}, "balance": 500000.0, "available_balance": 500000.0,
            },
            headers=admin_headers,
        )

        # 1. Admin Increase
        res_inc = await client.post(
            "/admin/users/trader_alpha/limit-increase",
            json={"segment": "option", "new_limit": 15},
            headers=admin_headers,
        )
        assert res_inc.status_code == 200
        assert res_inc.json()["action"] == "LIMIT_INCREASE"

        # 2. Admin Revoke / Lower
        res_rev = await client.post(
            "/admin/users/trader_alpha/limit-revoke",
            json={"segment": "option", "new_limit": 5},
            headers=admin_headers,
        )
        assert res_rev.status_code == 200
        assert res_rev.json()["action"] == "LIMIT_REVOKE"

        # Verify audit logs in database
        res_audit = await client.get("/admin/audit-logs?target_user_id=trader_alpha", headers=admin_headers)
        assert res_audit.status_code == 200
        actions = [log["action"] for log in res_audit.json()["audit_logs"]]
        assert "LIMIT_INCREASE" in actions
        assert "LIMIT_REVOKE" in actions


@pytest.mark.asyncio
async def test_08_buy_and_sell_trade_pnl_computation():
    """8. Closing a BUY trade and a SELL trade both compute pnl correctly."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    token = create_access_token(user_id="trader_pnl", role="user")
    headers = {"Authorization": f"Bearer {token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/admin/users",
            json={
                "user_id": "trader_pnl",
                "password": "Password@123",
                "name": "PNL Trader",
                "allowed_segments": ["option"],
                "trade_limit": {"option": 10, "future": 0, "cash": 0}, "balance": 500000.0, "available_balance": 500000.0,
            },
            headers=admin_headers,
        )

        # Case A: BUY Trade (Entry=100, Exit=125)
        with patch("routers.user_routes.angel_client.get_ltp", side_effect=[100.0, 125.0]), \
             patch("market_calendar.is_market_open", return_value=True):
            res_buy = await client.post(
                "/user/trade/option",
                json={"instrument": "NIFTY", "expiry": "28MAR2026", "strike": 22500.0, "option_type": "CE", "action": "BUY", "qty": 25},
                headers=headers,
            )
            buy_trade = res_buy.json()["trade"]
            buy_trade_id = buy_trade["trade_id"]
            res_close_buy = await client.post(f"/user/trade/option/{buy_trade_id}/close", headers=headers)
            assert res_close_buy.status_code == 200
            expected_buy_pnl = round((125.0 - 100.0) * buy_trade["pnl_qty"], 2)
            assert res_close_buy.json()["trade"]["pnl"] == expected_buy_pnl

        # Case B: SELL Trade (Entry=200, Exit=160)
        with patch("routers.user_routes.angel_client.get_ltp", side_effect=[200.0, 160.0]), \
             patch("market_calendar.is_market_open", return_value=True):
            res_sell = await client.post(
                "/user/trade/option",
                json={"instrument": "NIFTY", "expiry": "28MAR2026", "strike": 22500.0, "option_type": "PE", "action": "SELL", "qty": 25},
                headers=headers,
            )
            sell_trade = res_sell.json()["trade"]
            sell_trade_id = sell_trade["trade_id"]
            res_close_sell = await client.post(f"/user/trade/option/{sell_trade_id}/close", headers=headers)
            assert res_close_sell.status_code == 200
            expected_sell_pnl = round((200.0 - 160.0) * sell_trade["pnl_qty"], 2)
            assert res_close_sell.json()["trade"]["pnl"] == expected_sell_pnl


@pytest.mark.asyncio
async def test_09_force_close_all_trades_across_segments():
    """9. Force-close-all closes every open trade across all 3 segments for a user."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    token = create_access_token(user_id="trader_force", role="user")
    headers = {"Authorization": f"Bearer {token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create user with all 3 segments
        await client.post(
            "/admin/users",
            json={
                "user_id": "trader_force",
                "password": "Password@123",
                "name": "Force Trader",
                "allowed_segments": ["option", "future", "cash"],
                "trade_limit": {"option": 5, "future": 5, "cash": 50000}, "balance": 500000.0, "available_balance": 500000.0,
                "balance": 500000.0,
                "available_balance": 500000.0,
            },
            headers=admin_headers,
        )

        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0), \
             patch("market_calendar.is_market_open", return_value=True):
            # Open 1 Option, 1 Future, 1 Cash trade
            await client.post(
                "/user/trade/option",
                json={"instrument": "NIFTY", "expiry": "28MAR2026", "strike": 22500.0, "option_type": "CE", "action": "BUY", "qty": 25},
                headers=headers,
            )
            await client.post(
                "/user/trade/future",
                json={"instrument": "BANKNIFTY", "expiry": "28MAR2026", "action": "SELL", "qty": 15},
                headers=headers,
            )
            await client.post(
                "/user/trade/cash",
                json={"instrument": "NIFTY", "action": "BUY", "qty": 10},
                headers=headers,
            )

        with patch("routers.admin_routes.angel_client.get_ltp", return_value=110.0), \
             patch("market_calendar.is_market_open", return_value=True):
            # Admin triggers force-close-all
            res_force = await client.post("/admin/users/trader_force/force-close-all", headers=admin_headers)
            assert res_force.status_code == 200
            summary = res_force.json()["summary"]
            assert summary["total_closed"] == 3
            assert summary["option"] == 1
            assert summary["future"] == 1
            assert summary["cash"] == 1

        # Verify all collections have 0 OPEN trades for trader_force
        db = get_db()
        for seg in ["option", "future", "cash"]:
            open_count = await db[f"trades_{seg}"].count_documents({"user_id": "trader_force", "status": "OPEN"})
            assert open_count == 0


@pytest.mark.asyncio
async def test_10_user_isolation_cannot_fetch_or_close_other_user_trades():
    """10. A user cannot fetch or close another user's trades regardless of request params."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create User Alpha & User Beta
        await client.post(
            "/admin/users",
            json={"user_id": "trader_alpha", "password": "Password@123", "name": "Alpha", "allowed_segments": ["option"], "trade_limit": {"option": 5, "future": 0, "cash": 0}, "balance": 500000.0, "available_balance": 500000.0,
                "balance": 500000.0,
                "available_balance": 500000.0},
            headers=admin_headers,
        )
        await client.post(
            "/admin/users",
            json={"user_id": "trader_beta", "password": "Password@123", "name": "Beta", "allowed_segments": ["option"], "trade_limit": {"option": 5, "future": 0, "cash": 0}, "balance": 500000.0, "available_balance": 500000.0,
                "balance": 500000.0,
                "available_balance": 500000.0},
            headers=admin_headers,
        )

        alpha_token = create_access_token(user_id="trader_alpha", role="user")
        beta_token = create_access_token(user_id="trader_beta", role="user")

        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0):
            # User Alpha places a trade
            res_alpha_trade = await client.post(
                "/user/trade/option",
                json={"instrument": "NIFTY", "expiry": "28MAR2026", "strike": 22500.0, "option_type": "CE", "action": "BUY", "qty": 25},
                headers={"Authorization": f"Bearer {alpha_token}"},
            )
            alpha_trade_id = res_alpha_trade.json()["trade"]["trade_id"]

            # User Beta attempts to list trades (even passing ?user_id=trader_alpha)
            res_beta_list = await client.get(
                "/user/trades/option?user_id=trader_alpha",
                headers={"Authorization": f"Bearer {beta_token}"},
            )
            assert res_beta_list.status_code == 200
            # Must return empty list for Beta
            assert len(res_beta_list.json()["trades"]) == 0

            # User Beta attempts to close User Alpha's trade -> 404 Not Found
            res_beta_close = await client.post(
                f"/user/trade/option/{alpha_trade_id}/close",
                headers={"Authorization": f"Bearer {beta_token}"},
            )
            assert res_beta_close.status_code == 404


@pytest.mark.asyncio
async def test_11_non_admin_token_hitting_admin_route_returns_403():
    """11. Non-admin JWT hitting an admin endpoint returns 403."""
    await reset_test_db()
    user_headers = get_user_headers("trader_alpha")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Regular user hitting GET /admin/users
        res_list = await client.get("/admin/users", headers=user_headers)
        assert res_list.status_code == 403
        assert "Admin privileges required" in res_list.json()["detail"]

        # Regular user hitting POST /admin/users
        res_create = await client.post(
            "/admin/users",
            json={"user_id": "hacker", "password": "123", "name": "Hack", "allowed_segments": [], "trade_limit": {}},
            headers=user_headers,
        )
        assert res_create.status_code == 403


@pytest.mark.asyncio
async def test_12_password_hash_never_appears_in_responses():
    """12. password_hash never appears in any response body."""
    await reset_test_db()
    admin_headers = get_admin_headers()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create user
        res_create = await client.post(
            "/admin/users",
            json={
                "user_id": "trader_sec",
                "password": "UltraSecretPassword!123",
                "name": "Security Test",
                "allowed_segments": ["option"],
                "trade_limit": {"option": 5, "future": 0, "cash": 0}, "balance": 500000.0, "available_balance": 500000.0,
                "balance": 500000.0,
                "available_balance": 500000.0,
            },
            headers=admin_headers,
        )
        assert "password_hash" not in res_create.text
        assert "UltraSecretPassword" not in res_create.text

        # List users
        res_list = await client.get("/admin/users", headers=admin_headers)
        assert "password_hash" not in res_list.text

        # Get user detail
        res_detail = await client.get("/admin/users/trader_sec", headers=admin_headers)
        assert "password_hash" not in res_detail.text

        # User Login
        res_login = await client.post(
            "/user/login",
            json={"user_id": "trader_sec", "password": "UltraSecretPassword!123"},
        )
        assert "password_hash" not in res_login.text
