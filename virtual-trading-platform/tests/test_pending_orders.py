"""Tests for Pending (Limit) Orders, Mutex Modification, Background Order Engine, and Concurrency Races.
Covers:
  1. Placing a pending order reserves exactly R = lock + brokerage.
  2. Multiple pending orders cannot reserve more than balance (shortfall guard).
  3. Marketable limit order fills immediately when market is open.
  4. Market closed keeps order in PENDING without filling.
  5. Cancel releases reserved amount exactly once.
  6. Cancel vs. Fill race condition (asyncio.gather): exactly one wins, balances remain consistent.
  7. Modify vs. Fill race condition (asyncio.gather): mutex ensures no corruption.
  8. Stale price (>10s or not live) prevents fill.
  9. Fill-time guard failure marks order REJECTED and refunds full reserved amount.
  10. Auto square-off cancels all user pending orders first before positions close.
  11. Admin cancel endpoint cancels order and refunds reserved amount.
  12. Modifying order mutex timeout recovery (sweep returns to PENDING after 30s).
"""
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo
import pytest
from httpx import ASGITransport, AsyncClient

from auth import create_access_token
from db import get_db
from main import app
from order_engine import (
    cancel_all_user_pending_orders,
    run_order_cycle,
)
from market_calendar import IST

MOCK_OPEN_TIME = datetime(2026, 9, 30, 11, 0, 0, tzinfo=IST)
MOCK_CLOSED_TIME = datetime(2026, 9, 30, 8, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
async def setup_clean_orders_db():
    db = get_db()
    test_prefix = "ord_test_"
    await db.users.delete_many({"user_id": {"$regex": f"^{test_prefix}"}})
    for seg in ["option", "future", "cash"]:
        await db[f"trades_{seg}"].delete_many({"user_id": {"$regex": f"^{test_prefix}"}})
    await db.orders.delete_many({"user_id": {"$regex": f"^{test_prefix}"}})
    await db.brokerage_config.delete_many({})
    yield
    await db.brokerage_config.delete_many({})


# ---------------------------------------------------------------------------
# 1. Placing Pending Order Reserves Exactly R = Lock + Brokerage
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_place_pending_order_reserves_exact_amount():
    db = get_db()
    u_id = "ord_test_user_place"
    initial_balance = 100000.0

    await db.users.insert_one({
        "user_id": u_id,
        "name": "Limit Trader",
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option", "future"],
        "allowed_instrument_types": ["INDEX"],
    })

    # Brokerage: ₹20 / lot
    await db.brokerage_config.insert_one({
        "scope": "user",
        "user_id": u_id,
        "segment": "option",
        "instrument_type": "INDEX",
        "mode": "PER_LOT",
        "value": 20.0,
        "enabled": True,
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    headers = {"Authorization": f"Bearer {user_token}"}

    # Market is open, but limit price is 50.0 and LTP is 100.0 (BUY limit < LTP -> NOT marketable, stays PENDING)
    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={
                        "instrument": "NIFTY",
                        "action": "BUY",
                        "limit_price": 50.0,
                        "lots": 2,
                    },
                )
                assert res.status_code == 200, res.text
                data = res.json()["order"]
                assert data["status"] == "PENDING"
                # Lock = 2 lots * 65 lot_size * 50.0 limit_price = 6,500.0
                # Brokerage = 2 lots * 20.0 = 40.0
                # R = 6,540.0
                assert data["reserved_lock"] == 6500.0
                assert data["reserved_brokerage"] == 40.0
                assert data["reserved_total"] == 6540.0

                user_fresh = await db.users.find_one({"user_id": u_id})
                assert user_fresh["available_balance"] == round(initial_balance - 6540.0, 2)
                assert user_fresh["margin_blocked"] == 6540.0


# ---------------------------------------------------------------------------
# 2. Marketable Limit Order Fills Immediately via open_position
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_marketable_limit_order_fills_immediately():
    db = get_db()
    u_id = "ord_test_user_marketable"
    initial_balance = 100000.0

    await db.users.insert_one({
        "user_id": u_id,
        "name": "Marketable Trader",
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    headers = {"Authorization": f"Bearer {user_token}"}

    # BUY Limit = 110.0, Live LTP = 100.0 (Limit >= LTP -> Marketable, executes at 100.0)
    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={
                        "instrument": "NIFTY",
                        "action": "BUY",
                        "limit_price": 110.0,
                        "lots": 1,
                    },
                )
                assert res.status_code == 200, res.text
                res_data = res.json()
                assert "immediately" in res_data["message"]
                order = res_data["order"]
                trade = res_data["trade"]
                assert order["status"] == "EXECUTED"
                assert order["executed_price"] == 100.0
                assert order["trade_id"] == trade["trade_id"]
                assert trade["entry_price"] == 100.0
                assert trade["source"] == "LIMIT_ORDER"


# ---------------------------------------------------------------------------
# 3. Market Closed -> Always PENDING
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_market_closed_stays_pending():
    db = get_db()
    u_id = "ord_test_user_closed"
    initial_balance = 100000.0

    await db.users.insert_one({
        "user_id": u_id,
        "name": "Closed Market Trader",
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    headers = {"Authorization": f"Bearer {user_token}"}

    # Limit = 150.0 even if > LTP, but Market is CLOSED -> stays PENDING
    with patch("market_calendar.now_ist", return_value=MOCK_CLOSED_TIME):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={
                        "instrument": "NIFTY",
                        "action": "BUY",
                        "limit_price": 150.0,
                        "lots": 1,
                    },
                )
                assert res.status_code == 200
                order = res.json()["order"]
                assert order["status"] == "PENDING"
                assert order["trade_id"] is None


# ---------------------------------------------------------------------------
# 4. Cancel Releases Reservation Exactly Once
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cancel_pending_order_releases_once():
    db = get_db()
    u_id = "ord_test_user_cancel"
    initial_balance = 100000.0

    await db.users.insert_one({
        "user_id": u_id,
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    headers = {"Authorization": f"Bearer {user_token}"}

    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=200.0):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={"instrument": "NIFTY", "action": "BUY", "limit_price": 50.0, "lots": 1},
                )
                order_id = res.json()["order"]["order_id"]
                r = res.json()["order"]["reserved_total"]

                # Balance reduced by r
                user_post = await db.users.find_one({"user_id": u_id})
                assert user_post["available_balance"] == round(initial_balance - r, 2)

                # 1. First Cancel -> 200 OK
                del_res = await ac.delete(f"/user/order/{order_id}", headers=headers)
                assert del_res.status_code == 200
                user_refunded = await db.users.find_one({"user_id": u_id})
                assert user_refunded["available_balance"] == initial_balance
                assert user_refunded["margin_blocked"] == 0.0

                # 2. Second Cancel -> 409 Conflict (already cancelled)
                del_res_2 = await ac.delete(f"/user/order/{order_id}", headers=headers)
                assert del_res_2.status_code in (400, 409)

                # Balance still initial_balance, not double refunded!
                user_check = await db.users.find_one({"user_id": u_id})
                assert user_check["available_balance"] == initial_balance


# ---------------------------------------------------------------------------
# 5. Cancel vs. Fill Race (Real asyncio.gather)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cancel_vs_fill_race_safety():
    db = get_db()
    u_id = "ord_test_user_race_cf"
    initial_balance = 50000.0

    await db.users.insert_one({
        "user_id": u_id,
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    headers = {"Authorization": f"Bearer {user_token}"}

    # Place order: BUY limit = 50.0, LTP starts at 100.0
    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={"instrument": "NIFTY", "action": "BUY", "limit_price": 50.0, "lots": 1},
                )
                order_id = res.json()["order"]["order_id"]

    # Now launch simultaneous Cancel vs Order Cycle Fill (LTP drops to 45.0)
    meta_live = {
        "price": 45.0,
        "source": "live",
        "fetched_at": datetime.now(timezone.utc),
    }

    async def do_cancel():
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.delete(f"/user/order/{order_id}", headers=headers)

    async def do_engine_fill():
        with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
            with patch("order_engine.angel_client.get_ltp_with_meta", return_value=meta_live):
                await run_order_cycle()

    # Run simultaneously
    cancel_res, _ = await asyncio.gather(do_cancel(), do_engine_fill())

    order_doc = await db.orders.find_one({"order_id": order_id})
    user_fresh = await db.users.find_one({"user_id": u_id})

    # Exactly one status: either CANCELLED or EXECUTED
    assert order_doc["status"] in ("CANCELLED", "EXECUTED")

    if order_doc["status"] == "CANCELLED":
        # Full refund to initial balance
        assert user_fresh["available_balance"] == initial_balance
        assert user_fresh["margin_blocked"] == 0.0
        # No trade was inserted
        trade_count = await db.trades_option.count_documents({"order_id": order_id})
        assert trade_count == 0
    else:
        # EXECUTED: trade inserted, margin blocked equals trade requirement
        trade = await db.trades_option.find_one({"order_id": order_id})
        assert trade is not None
        assert user_fresh["margin_blocked"] == trade["margin_blocked_amount"]


# ---------------------------------------------------------------------------
# 6. Stale Price Prevents Fill
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stale_price_prevents_fill():
    db = get_db()
    u_id = "ord_test_user_stale"
    initial_balance = 50000.0

    await db.users.insert_one({
        "user_id": u_id,
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    headers = {"Authorization": f"Bearer {user_token}"}

    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={"instrument": "NIFTY", "action": "BUY", "limit_price": 50.0, "lots": 1},
                )
                order_id = res.json()["order"]["order_id"]

    # Price is 45.0 (trigger met), but fetched_at is 15 seconds ago (> 10s stale limit)
    stale_meta = {
        "price": 45.0,
        "source": "live",
        "fetched_at": datetime.now(timezone.utc) - timedelta(seconds=15),
    }

    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("order_engine.angel_client.get_ltp_with_meta", return_value=stale_meta):
            await run_order_cycle()

    # Order must NOT be filled!
    order_doc = await db.orders.find_one({"order_id": order_id})
    assert order_doc["status"] == "PENDING"


# ---------------------------------------------------------------------------
# 7. Fill-Time Insufficient Funds Rejects and Refunds R
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fill_time_insufficient_funds_rejects_and_refunds():
    """Fill-time rejection due to price-movement shortfall:
    1. User places an OPTION limit order at P1=50.0, qty=50 (1 lot).
       Reserve R1 = (50.0 * 50) + entry_brokerage is locked. Confirm exact R1 from brokerage config.
    2. Mock live price moves UP to P2=54.0, making the order marketable at 54.0.
       Required at fill: R2 = (54.0 * 50) + entry_brokerage, creating a genuine shortfall
       delta_needed = R2 - R1 = 200.0 constructed entirely by the price move (not external balance withdrawal).
    3. User's available_balance before fill is enough to cover R1 but short of (R2 - R1).
    4. Run real order engine cycle (run_order_cycle()).
    5. Assert:
       - order.status == "REJECTED"
       - order.reject_reason contains the actual shortfall figure (200.00)
       - available_balance returns to exactly pre-order value
       - margin_blocked returns to 0.0
    """
    from trade_engine import compute_brokerage, resolve_brokerage_config

    db = get_db()
    u_id = "ord_test_user_shortfill"
    await db.users.delete_many({"user_id": u_id})
    await db.orders.delete_many({"user_id": u_id})
    await db.brokerage_config.delete_many({"scope": "global", "segment": "option"})

    # Setup standard brokerage config: 20 per lot on option
    await db.brokerage_config.insert_one({
        "scope": "global",
        "segment": "option",
        "instrument_type": "INDEX",
        "mode": "PER_LOT",
        "value": 20.0,
        "enabled": True,
        "updated_at": datetime.now(timezone.utc),
    })

    # Resolve expected brokerage from real config
    brok_cfg = await resolve_brokerage_config(u_id, "option", "INDEX")
    expected_entry_brok = compute_brokerage(brok_cfg, 50.0, 1, 50.0)
    assert expected_entry_brok == 20.0

    # R1 = (50.0 * 50) + 20.0 = 2520.0
    expected_r1 = round((50.0 * 50) + expected_entry_brok, 2)
    assert expected_r1 == 2520.0

    # User balance is funded with exactly enough to cover R1, leaving available_balance = 0 after placement
    initial_balance = expected_r1
    await db.users.insert_one({
        "user_id": u_id,
        "name": "Shortfall User",
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    headers = {"Authorization": f"Bearer {user_token}"}

    # 1. Place order at limit 50.0 (unmarketable when live market is 40.0)
    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=40.0):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={"instrument": "NIFTY", "action": "SELL", "limit_price": 50.0, "lots": 1, "qty": 50},
                )
                assert res.status_code == 200
                order_id = res.json()["order"]["order_id"]
                r1 = res.json()["order"]["reserved_total"]
                assert r1 == expected_r1

    # Verify user state after order placement
    user_after_order = await db.users.find_one({"user_id": u_id})
    assert user_after_order["available_balance"] == 0.0
    assert user_after_order["margin_blocked"] == expected_r1

    # 2. Live price moves UP to P2=54.0, becoming marketable
    # Required at fill: R2 = (54.0 * 50) + 20.0 = 2720.0
    # Genuine shortfall: R2 - R1 = 200.00
    expected_r2 = round((54.0 * 50) + expected_entry_brok, 2)
    expected_shortfall = round(expected_r2 - expected_r1, 2)
    assert expected_shortfall == 200.0

    meta_live = {"price": 54.0, "source": "live", "fetched_at": datetime.now(timezone.utc)}

    # 3 & 4. Run real order engine cycle with live price at 54.0
    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("order_engine.angel_client.get_ltp_with_meta", return_value=meta_live):
            await run_order_cycle()

    # 5. Assert: order is REJECTED, reject_reason has exact shortfall, and full R1 is refunded
    order_doc = await db.orders.find_one({"order_id": order_id})
    assert order_doc["status"] == "REJECTED"
    assert f"required additional ₹{expected_shortfall:,.2f}" in order_doc["reject_reason"]

    user_fresh = await db.users.find_one({"user_id": u_id})
    assert user_fresh["available_balance"] == initial_balance
    assert user_fresh["margin_blocked"] == 0.0


# ---------------------------------------------------------------------------
# 8. Auto Square-Off Cancels Pending Orders First
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_auto_square_off_cancels_pending_orders_first():
    db = get_db()
    u_id = "ord_test_user_autosq_pend"
    balance = 100000.0

    await db.users.insert_one({
        "user_id": u_id,
        "balance": balance,
        "available_balance": balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    headers = {"Authorization": f"Bearer {user_token}"}

    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=200.0):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={"instrument": "NIFTY", "action": "BUY", "limit_price": 50.0, "lots": 1},
                )
                order_id = res.json()["order"]["order_id"]
                r = res.json()["order"]["reserved_total"]

    # Call cancel_all_user_pending_orders (which is called by auto square-off and admin force close)
    cancelled = await cancel_all_user_pending_orders(u_id, cancelled_by="SYSTEM_AUTO_SQUARE_OFF")
    assert cancelled == 1

    order_doc = await db.orders.find_one({"order_id": order_id})
    assert order_doc["status"] == "CANCELLED"
    assert order_doc["cancelled_by"] == "SYSTEM_AUTO_SQUARE_OFF"

    user_fresh = await db.users.find_one({"user_id": u_id})
    assert user_fresh["available_balance"] == balance
    assert user_fresh["margin_blocked"] == 0.0


# ---------------------------------------------------------------------------
# 9. Admin Cancel Endpoint Works
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_cancel_endpoint():
    db = get_db()
    u_id = "ord_test_user_admin_cancel"
    balance = 100000.0

    await db.users.insert_one({
        "user_id": u_id,
        "balance": balance,
        "available_balance": balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    admin_token = create_access_token("admin", "admin")
    u_headers = {"Authorization": f"Bearer {user_token}"}
    a_headers = {"Authorization": f"Bearer {admin_token}"}

    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=200.0):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/user/order/option",
                    headers=u_headers,
                    json={"instrument": "NIFTY", "action": "BUY", "limit_price": 50.0, "lots": 1},
                )
                order_id = res.json()["order"]["order_id"]

                # Admin cancels
                del_res = await ac.post(f"/admin/users/{u_id}/orders/{order_id}/cancel", headers=a_headers)
                assert del_res.status_code == 200
                assert del_res.json()["order"]["status"] == "CANCELLED"

                # Check refund
                user_fresh = await db.users.find_one({"user_id": u_id})
                assert user_fresh["available_balance"] == balance
                assert user_fresh["margin_blocked"] == 0.0


# ---------------------------------------------------------------------------
# 10. Modify vs. Fill Race (asyncio.gather)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_modify_vs_fill_race_safety():
    """Strengthened concurrency race test:
    Simultaneously runs do_modify() (PENDING -> MODIFYING -> PENDING) and do_fill() (PENDING -> EXECUTED).
    Asserts:
    1. If EXECUTED: mod_res must be 409 Conflict with 'EXECUTED' in detail, and resulting trade entry_price reflects
       the original 50.0-limit fill logic (52.0), NOT 55.0 (proving modify never leaked into fill).
    2. If PENDING: mod_res must be 200 OK, order limit_price == 55.0, and no trade doc created.
    3. Runs 25 iterations to verify mutex safety under real timing variations.
    """
    db = get_db()
    initial_balance = 50000.0
    transport = ASGITransport(app=app)

    executed_count = 0
    pending_count = 0

    for iteration in range(25):
        u_id = f"ord_test_user_mod_race_{iteration}"
        await db.users.delete_many({"user_id": u_id})
        await db.orders.delete_many({"user_id": u_id})
        await db.trades_option.delete_many({"user_id": u_id})

        await db.users.insert_one({
            "user_id": u_id,
            "balance": initial_balance,
            "available_balance": initial_balance,
            "margin_blocked": 0.0,
            "realized_pnl": 0.0,
            "total_brokerage_paid": 0.0,
            "allowed_segments": ["option"],
            "allowed_instrument_types": ["INDEX"],
        })

        user_token = create_access_token(u_id, "user")
        headers = {"Authorization": f"Bearer {user_token}"}

        # Place initial SELL order at limit 50.0 (unmarketable when live market is 40.0)
        with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
            with patch("routers.user_routes.angel_client.get_ltp", return_value=40.0):
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    res = await ac.post(
                        "/user/order/option",
                        headers=headers,
                        json={"instrument": "NIFTY", "action": "SELL", "limit_price": 50.0, "lots": 1},
                    )
                    assert res.status_code == 200
                    order_id = res.json()["order"]["order_id"]

        # Simultaneous Modify (limit price increases to 55.0) and Engine Fill (market price rises to 52.0)
        # Note for SELL limit order:
        # - Market price 52.0 triggers original limit (52.0 >= 50.0).
        # - Market price 52.0 DOES NOT trigger modified limit (52.0 < 55.0).
        # Therefore, exactly ONE outcome occurs:
        # - Either Fill claims first -> EXECUTED at 52.0, Modify gets 409 Conflict.
        # - Or Modify claims first -> PENDING at 55.0, Fill does not trigger.
        meta_live = {"price": 52.0, "source": "live", "fetched_at": datetime.now(timezone.utc)}

        mod_delay = 0.003 if iteration % 2 == 0 else 0.0
        fill_delay = 0.003 if iteration % 2 == 1 else 0.0

        async def do_modify():
            if mod_delay > 0:
                await asyncio.sleep(mod_delay)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                return await ac.put(f"/user/order/{order_id}", headers=headers, json={"limit_price": 55.0})

        async def do_fill():
            if fill_delay > 0:
                await asyncio.sleep(fill_delay)
            with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
                with patch("order_engine.angel_client.get_ltp_with_meta", return_value=meta_live):
                    await run_order_cycle()

        mod_res, _ = await asyncio.gather(do_modify(), do_fill())

        order_doc = await db.orders.find_one({"order_id": order_id})
        user_fresh = await db.users.find_one({"user_id": u_id})

        if order_doc["status"] == "EXECUTED":
            executed_count += 1
            # Fill claimed mutex first: modify must be cleanly rejected with 409 Conflict
            assert mod_res.status_code == 409
            assert "Order cannot be modified" in mod_res.json()["detail"]
            assert "EXECUTED" in mod_res.json()["detail"]

            # Resulting trade entry_price reflects the original 50.0-limit fill logic (52.0), NOT 55.0
            trade = await db.trades_option.find_one({"order_id": order_id})
            assert trade is not None
            assert trade["entry_price"] == 52.0
            assert trade["entry_price"] != 55.0

        elif order_doc["status"] == "PENDING":
            pending_count += 1
            # Modify claimed mutex first: modify applied cleanly with 200 OK
            assert mod_res.status_code == 200
            assert order_doc["limit_price"] == 55.0

            # No trade was created because 52.0 < new limit 55.0
            trade = await db.trades_option.find_one({"order_id": order_id})
            assert trade is None
        else:
            pytest.fail(f"Invalid order status {order_doc['status']} in iteration {iteration}")

        # In both outcomes: user balance must be 100% reconciled without any leakage
        tot_brok = user_fresh.get("total_brokerage_paid", 0.0)
        assert round(user_fresh["available_balance"] + user_fresh["margin_blocked"] + tot_brok, 2) == initial_balance

    # Ensure both outcomes were actively exercised across the 25 iterations
    print(f"\n[Race Safety Loop] 25 iterations completed: Fill-won (409 rejected modify)={executed_count}, Modify-won (order remained PENDING at 55.0)={pending_count}")
    assert executed_count > 0
    assert pending_count > 0
    assert executed_count + pending_count == 25


# ---------------------------------------------------------------------------
# 11. Multiple Pending Orders Cannot Exceed Balance
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multiple_pending_orders_cannot_exceed_balance():
    db = get_db()
    u_id = "ord_test_user_multi_cap"
    initial_balance = 7000.0  # Just enough for one order (~3,250)

    await db.users.insert_one({
        "user_id": u_id,
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option"],
        "allowed_instrument_types": ["INDEX"],
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    headers = {"Authorization": f"Bearer {user_token}"}

    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        with patch("routers.user_routes.angel_client.get_ltp", return_value=100.0):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                # Order 1: 50.0 * 65 = 3,250 -> succeeds, balance left = 3,750
                res1 = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={"instrument": "NIFTY", "action": "BUY", "limit_price": 50.0, "lots": 1},
                )
                assert res1.status_code == 200

                # Order 2: 50.0 * 65 = 3,250 -> succeeds, balance left = 500
                res2 = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={"instrument": "NIFTY", "action": "BUY", "limit_price": 50.0, "lots": 1},
                )
                assert res2.status_code == 200

                # Order 3: 50.0 * 65 = 3,250 -> fails with 400 Insufficient margin!
                res3 = await ac.post(
                    "/user/order/option",
                    headers=headers,
                    json={"instrument": "NIFTY", "action": "BUY", "limit_price": 50.0, "lots": 1},
                )
                assert res3.status_code == 400
                assert "Insufficient margin" in res3.json()["detail"]


# ---------------------------------------------------------------------------
# 12. Modifying Order Mutex 30s Timeout Recovery Sweep
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stale_modifying_sweep_reverts_to_pending():
    db = get_db()
    u_id = "ord_test_user_sweep"
    now_utc = datetime.now(timezone.utc)

    # Insert order stuck in MODIFYING for 35 seconds
    stuck_order_id = "ORD-OPT-STUCK30S"
    await db.orders.insert_one({
        "order_id": stuck_order_id,
        "user_id": u_id,
        "segment": "option",
        "instrument": "NIFTY",
        "tradingsymbol": "NIFTY26SEP24000CE",
        "exchange": "NFO",
        "symboltoken": "99901",
        "status": "MODIFYING",
        "limit_price": 50.0,
        "lots": 1,
        "qty": 65,
        "reserved_total": 3250.0,
        "version": 1,
        "modified_at": now_utc - timedelta(seconds=35),
        "history": [],
    })

    with patch("market_calendar.now_ist", return_value=MOCK_OPEN_TIME):
        await run_order_cycle()

    reverted = await db.orders.find_one({"order_id": stuck_order_id})
    assert reverted["status"] == "PENDING"
    assert any(h.get("action") == "MUTEX_TIMEOUT_REVERT" for h in reverted.get("history", []))

