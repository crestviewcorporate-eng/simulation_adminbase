import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from httpx import ASGITransport, AsyncClient

from main import app
from db import get_db
from auth import create_access_token
from angelone_client import LTPFetchError, BadSymbolTokenError
from mtm_engine import run_mtm_cycle


@pytest.fixture(autouse=True)
async def cleanup_db():
    db = get_db()
    test_user_id = "real_price_tester"
    await db.users.delete_many({"user_id": test_user_id})
    for seg in ("option", "future", "cash"):
        await db[f"trades_{seg}"].delete_many({"user_id": test_user_id})
    await db.audit_logs.delete_many({"target_user_id": test_user_id})
    yield
    await db.users.delete_many({"user_id": test_user_id})
    for seg in ("option", "future", "cash"):
        await db[f"trades_{seg}"].delete_many({"user_id": test_user_id})
    await db.audit_logs.delete_many({"target_user_id": test_user_id})


@pytest.mark.asyncio
async def test_quote_failure_order_rejected_balance_unchanged():
    """Requirement 4: Quote failure -> 502, order rejected, balance unchanged, no DB insertion."""
    db = get_db()
    user_id = "real_price_tester"
    now = datetime.now(timezone.utc)

    await db.users.insert_one({
        "user_id": user_id,
        "name": "Price Test User",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option", "future", "cash"],
        "balance": 100000.0,
        "available_balance": 100000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "equity": 100000.0,
        "loss_pct": 0.0,
        "created_at": now,
        "updated_at": now,
    })

    user_token = create_access_token(user_id=user_id, role="user")
    headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Option trade with LTPFetchError
        with patch("routers.user_routes.angel_client.get_ltp", side_effect=LTPFetchError("Broker connection timeout")):
            payload = {
                "instrument": "NIFTY",
                "expiry": "22SEP2026",
                "strike": 23300.0,
                "option_type": "CE",
                "action": "BUY",
                "lots": 1,
                "qty": 65,
            }
            res = await client.post("/user/trade/option", json=payload, headers=headers)
            assert res.status_code == 502
            assert res.json()["detail"] == "Live price unavailable, try again"

        # 2. Future trade with returned price <= 0
        with patch("routers.user_routes.angel_client.get_ltp", return_value=0.0):
            payload_fut = {
                "instrument": "NIFTY",
                "expiry": "22SEP2026",
                "action": "BUY",
                "lots": 1,
            }
            res_fut = await client.post("/user/trade/future", json=payload_fut, headers=headers)
            assert res_fut.status_code == 502
            assert res_fut.json()["detail"] == "Live price unavailable, try again"

        # Verify DB state: balance completely unchanged, 0 trades inserted
        user_doc = await db.users.find_one({"user_id": user_id})
        assert user_doc["available_balance"] == 100000.0
        assert user_doc["margin_blocked"] == 0.0

        for seg in ("option", "future", "cash"):
            count = await db[f"trades_{seg}"].count_documents({"user_id": user_id})
            assert count == 0


@pytest.mark.asyncio
async def test_close_trade_price_failure_leaves_trade_open():
    """Requirement 5: close_trade on price failure returns 502 and leaves trade OPEN."""
    db = get_db()
    user_id = "real_price_tester"
    now = datetime.now(timezone.utc)

    await db.users.insert_one({
        "user_id": user_id,
        "name": "Price Test User",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option", "future", "cash"],
        "balance": 100000.0,
        "available_balance": 90000.0,
        "margin_blocked": 10000.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "equity": 100000.0,
        "loss_pct": 0.0,
        "created_at": now,
        "updated_at": now,
    })

    trade_id = "TRD-OPT-CLOSE-FAIL-1"
    await db.trades_option.insert_one({
        "trade_id": trade_id,
        "user_id": user_id,
        "segment": "option",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26MAR22500CE",
        "exchange": "NFO",
        "symboltoken": "55555",
        "action": "BUY",
        "qty": 50,
        "entry_price": 200.0,
        "entry_time": now,
        "exit_price": None,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 10000.0,
        "created_at": now,
        "updated_at": now,
    })

    user_token = create_access_token(user_id=user_id, role="user")
    headers = {"Authorization": f"Bearer {user_token}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Exit price quote fails
        with patch("routers.user_routes.angel_client.get_ltp", side_effect=LTPFetchError("Broker network disconnect")):
            res = await client.post(f"/user/trade/option/{trade_id}/close", headers=headers)
            assert res.status_code == 502
            assert res.json()["detail"] == "Live price unavailable, try again"

        # Verify trade remains OPEN with no fake exit price
        trade_doc = await db.trades_option.find_one({"trade_id": trade_id})
        assert trade_doc["status"] == "OPEN"
        assert trade_doc["exit_price"] is None
        assert trade_doc["pnl"] == 0.0

        # Verify user balances are completely untouched
        user_doc = await db.users.find_one({"user_id": user_id})
        assert user_doc["available_balance"] == 90000.0
        assert user_doc["margin_blocked"] == 10000.0
        assert user_doc["realized_pnl"] == 0.0


@pytest.mark.asyncio
async def test_mtm_missing_price_sets_mtm_stale_and_skips_auto_square_off():
    """Requirement 6: MTM with missing price keeps last good values, sets mtm_stale=True, and skips auto square-off."""
    db = get_db()
    user_id = "real_price_tester"
    now = datetime.now(timezone.utc)

    # User with last good unrealized=-35000, equity=15000, loss_pct=70% (threshold 80%)
    await db.users.insert_one({
        "user_id": user_id,
        "name": "MTM Stale User",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option", "future"],
        "balance": 50000.0,
        "available_balance": 10000.0,
        "margin_blocked": 40000.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": -35000.0,
        "equity": 15000.0,
        "loss_pct": 70.0,
        "auto_square_off_pct": 80.0,
        "mtm_stale": False,
        "last_auto_square_off_at": None,
        "created_at": now,
        "updated_at": now,
    })

    # Trade 1: Has price
    await db.trades_option.insert_one({
        "trade_id": "TRD-OPT-T1",
        "user_id": user_id,
        "segment": "option",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26MAR22500CE",
        "exchange": "NFO",
        "symboltoken": "1001",
        "action": "BUY",
        "qty": 50,
        "entry_price": 100.0,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 5000.0,
        "created_at": now,
        "updated_at": now,
    })

    # Trade 2: Missing price (fails fetch)
    await db.trades_future.insert_one({
        "trade_id": "TRD-FUT-T2",
        "user_id": user_id,
        "segment": "future",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26MARFUT",
        "exchange": "NFO",
        "symboltoken": "1002",
        "action": "BUY",
        "qty": 50,
        "entry_price": 22000.0,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 35000.0,
        "created_at": now,
        "updated_at": now,
    })

    def mock_fetch(exchange, tradingsymbol, symboltoken):
        if str(symboltoken) == "1001":
            return 10.0  # Big loss
        raise LTPFetchError("Exchange quote feed disconnected")

    with patch("mtm_engine.angel_client.get_ltp", side_effect=mock_fetch):
        await run_mtm_cycle()

    # User assertions: mtm_stale is True, mtm_updated_at set, last good values preserved
    user_doc = await db.users.find_one({"user_id": user_id})
    assert user_doc["mtm_stale"] is True
    assert user_doc["mtm_updated_at"] is not None
    assert user_doc["unrealized_pnl"] == -35000.0
    assert user_doc["equity"] == 15000.0

    # Crucial: Auto square-off was NOT triggered; both trades remain OPEN!
    opt_trade = await db.trades_option.find_one({"trade_id": "TRD-OPT-T1"})
    fut_trade = await db.trades_future.find_one({"trade_id": "TRD-FUT-T2"})
    assert opt_trade["status"] == "OPEN"
    assert fut_trade["status"] == "OPEN"


@pytest.mark.asyncio
async def test_bad_expired_token_sets_needs_settlement_on_trade():
    """Requirement 7: Bad/expired token sets needs_settlement=True on the trade without price substitution."""
    db = get_db()
    user_id = "real_price_tester"
    now = datetime.now(timezone.utc)

    await db.users.insert_one({
        "user_id": user_id,
        "name": "Bad Token User",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option"],
        "balance": 50000.0,
        "available_balance": 40000.0,
        "margin_blocked": 10000.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "equity": 50000.0,
        "loss_pct": 0.0,
        "auto_square_off_pct": 80.0,
        "mtm_stale": False,
        "created_at": now,
        "updated_at": now,
    })

    trade_id = "TRD-EXPIRED-TOKEN-1"
    await db.trades_option.insert_one({
        "trade_id": trade_id,
        "user_id": user_id,
        "segment": "option",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26MAR22500CE",
        "exchange": "NFO",
        "symboltoken": "99999_EXPIRED",
        "action": "BUY",
        "qty": 50,
        "entry_price": 150.0,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 7500.0,
        "needs_settlement": False,
        "created_at": now,
        "updated_at": now,
    })

    def mock_fetch_bad(exchange, tradingsymbol, symboltoken):
        raise BadSymbolTokenError(f"AB4046: Symbol token {symboltoken} not found or expired")

    with patch("mtm_engine.angel_client.get_ltp", side_effect=mock_fetch_bad):
        await run_mtm_cycle()

    # Trade assertion: needs_settlement is set to True
    trade_doc = await db.trades_option.find_one({"trade_id": trade_id})
    assert trade_doc["needs_settlement"] is True
    assert trade_doc["status"] == "OPEN"

    # User assertion: mtm_stale is set to True
    user_doc = await db.users.find_one({"user_id": user_id})
    assert user_doc["mtm_stale"] is True


@pytest.mark.asyncio
async def test_mtm_cycle_clears_mtm_stale_when_fresh_prices_recovered():
    """Requirement 6: Complete cycle with all fresh prices clears mtm_stale."""
    db = get_db()
    user_id = "real_price_tester"
    now = datetime.now(timezone.utc)

    # User was previously stale
    await db.users.insert_one({
        "user_id": user_id,
        "name": "Stale Recover User",
        "password_hash": "dummy",
        "is_active": True,
        "allowed_segments": ["option"],
        "balance": 50000.0,
        "available_balance": 45000.0,
        "margin_blocked": 5000.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "equity": 50000.0,
        "loss_pct": 0.0,
        "auto_square_off_pct": 80.0,
        "mtm_stale": True,
        "created_at": now,
        "updated_at": now,
    })

    trade_id = "TRD-RECOVER-1"
    await db.trades_option.insert_one({
        "trade_id": trade_id,
        "user_id": user_id,
        "segment": "option",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26MAR22500CE",
        "exchange": "NFO",
        "symboltoken": "8888",
        "action": "BUY",
        "qty": 50,
        "entry_price": 100.0,
        "status": "OPEN",
        "pnl": 0.0,
        "margin_blocked_amount": 5000.0,
        "created_at": now,
        "updated_at": now,
    })

    # Fresh price arrives: 110.0 (PnL = +500)
    with patch("mtm_engine.angel_client.get_ltp", return_value=110.0):
        await run_mtm_cycle()

    user_doc = await db.users.find_one({"user_id": user_id})
    assert user_doc["mtm_stale"] is False
    assert user_doc["unrealized_pnl"] == 500.0
    assert user_doc["equity"] == 50500.0
