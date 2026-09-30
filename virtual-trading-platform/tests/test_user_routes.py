import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from main import app
from db import get_db
from auth import hash_password, create_access_token


async def create_mock_user():
    db = get_db()
    await db.users.delete_many({"user_id": "test_trader_01"})
    await db.trades_option.delete_many({"user_id": "test_trader_01"})
    
    test_user_doc = {
        "user_id": "test_trader_01",
        "name": "Test Trader",
        "password_hash": hash_password("Password@123"),
        "is_active": True,
        "force_password_change": False,
        "allowed_segments": ["option", "future"],
        "allowed_instrument_types": ["INDEX", "MCX"],
        "trade_limit": {"option": 2, "future": 2, "cash": 0},
        "trades_used": {"option": 0, "future": 0, "cash": 0},
        "balance": 500000.0,
        "available_balance": 500000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "created_at": datetime.now(timezone.utc),
    }
    await db.users.insert_one(test_user_doc)


async def cleanup_mock_user():
    db = get_db()
    await db.users.delete_many({"user_id": "test_trader_01"})
    await db.trades_option.delete_many({"user_id": "test_trader_01"})


@pytest.mark.asyncio
async def test_user_login():
    await create_mock_user()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Invalid pass
            res = await client.post("/user/login", json={"user_id": "test_trader_01", "password": "WrongPassword"})
            assert res.status_code == 401

            # Valid pass
            res = await client.post("/user/login", json={"user_id": "test_trader_01", "password": "Password@123"})
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "success"
            assert "access_token" in data
            assert data["user_id"] == "test_trader_01"
    finally:
        await cleanup_mock_user()


@pytest.mark.asyncio
async def test_user_instruments_and_limit_status():
    await create_mock_user()
    try:
        token = create_access_token("test_trader_01", role="user")
        headers = {"Authorization": f"Bearer {token}"}
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Instruments
            res = await client.get("/user/instruments", headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "success"
            for inst in data["instruments"]:
                assert inst["segment"] in ["option", "future"]

            # Limit status
            res_limit = await client.get("/user/limit-status", headers=headers)
            assert res_limit.status_code == 200
            limit_data = res_limit.json()
            assert limit_data["remaining_limit"]["option"] == 2
    finally:
        await cleanup_mock_user()


@pytest.mark.asyncio
async def test_user_trade_execution_and_close():
    await create_mock_user()
    try:
        token = create_access_token("test_trader_01", role="user")
        headers = {"Authorization": f"Bearer {token}"}
        transport = ASGITransport(app=app)

        # Mock AngelOne get_ltp and market open
        with patch("routers.user_routes.angel_client.get_ltp", side_effect=[120.50, 135.50]), \
             patch("market_calendar.is_market_open", return_value=True):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 1. Trade Option Buy
                trade_payload = {
                    "instrument": "NIFTY",
                    "expiry": "28MAR2026",
                    "strike": 22500.0,
                    "option_type": "CE",
                    "action": "BUY",
                    "qty": 25,
                }
                res_trade = await client.post("/user/trade/option", json=trade_payload, headers=headers)
                assert res_trade.status_code == 200
                trade_info = res_trade.json()["trade"]
                assert trade_info["entry_price"] == 120.50
                assert trade_info["status"] == "OPEN"
                trade_id = trade_info["trade_id"]

                # 2. Check remaining limit is decremented to 1
                res_limit = await client.get("/user/limit-status", headers=headers)
                assert res_limit.json()["remaining_limit"]["option"] == 1

                # 3. Close the trade
                res_close = await client.post(f"/user/trade/option/{trade_id}/close", headers=headers)
                assert res_close.status_code == 200
                closed_trade = res_close.json()["trade"]
                assert closed_trade["status"] == "CLOSED"
                assert closed_trade["exit_price"] == 135.50
                # PnL = (135.50 - 120.50) * pnl_qty
                expected_pnl = round((135.50 - 120.50) * closed_trade["pnl_qty"], 2)
                assert closed_trade["pnl"] == expected_pnl

                # 4. View user trades
                res_trades = await client.get("/user/trades/option", headers=headers)
                assert res_trades.status_code == 200
                assert len(res_trades.json()["trades"]) >= 1
    finally:
        await cleanup_mock_user()


@pytest.mark.asyncio
async def test_trade_limit_exhaustion():
    await create_mock_user()
    try:
        token = create_access_token("test_trader_01", role="user")
        headers = {"Authorization": f"Bearer {token}"}
        transport = ASGITransport(app=app)

        db = get_db()
        await db.users.update_one({"user_id": "test_trader_01"}, {"$set": {"trades_used.option": 2}})

        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0), \
             patch("market_calendar.is_market_open", return_value=True):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                trade_payload = {
                    "instrument": "NIFTY",
                    "expiry": "28MAR2026",
                    "strike": 22500.0,
                    "option_type": "CE",
                    "action": "BUY",
                    "qty": 25,
                }
                res = await client.post("/user/trade/option", json=trade_payload, headers=headers)
                assert res.status_code in (400, 429)
                assert "Trade limit exhausted" in res.json()["detail"]
    finally:
        await cleanup_mock_user()
