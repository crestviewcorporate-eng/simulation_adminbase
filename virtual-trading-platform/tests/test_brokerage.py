"""Tests for Brokerage Configuration, Calculation, Accounting, and Admin/User Endpoints.
Covers:
  1. Brokerage math: PER_LOT and PERCENT (full contract value for futures/mcx).
  2. 5-tier resolution hierarchy (user+seg+type > user+seg > global+seg+type > global+seg > zero).
  3. Balance & Accounting atomicity on entry and exit (roundtrip verification).
  4. Shortfall error message format with separate Margin, Brokerage, Total, Available, Shortfall.
  5. Immutability: changing brokerage rate afterwards does not alter historical trade fields.
  6. Concurrent close race condition safety: exit brokerage is charged exactly once.
  7. Auto square-off charges exit brokerage correctly.
  8. Admin CRUD endpoints, audit logging with before/after state, and summary aggregation.
  9. User brokerage preview endpoint and limit-status total_brokerage_paid field.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient

from auth import create_access_token
from db import get_db
from main import app
from trade_engine import (
    compute_brokerage,
    resolve_brokerage_config,
    open_position,
    resolve_contract,
)
from mtm_engine import _close_single_trade


@pytest.fixture(autouse=True)
async def setup_clean_brokerage_db():
    db = get_db()
    test_prefix = "brok_test_"
    await db.users.delete_many({"user_id": {"$regex": f"^{test_prefix}"}})
    for seg in ["option", "future", "cash"]:
        await db[f"trades_{seg}"].delete_many({"user_id": {"$regex": f"^{test_prefix}"}})
    await db.brokerage_config.delete_many({})
    await db.audit_logs.delete_many({"details.test_data": True})
    yield
    await db.brokerage_config.delete_many({})



# ---------------------------------------------------------------------------
# 1. Calculation Math: PER_LOT and PERCENT
# ---------------------------------------------------------------------------
def test_brokerage_calc_per_lot_and_percent():
    # PER_LOT: ₹20 / lot, 2 lots -> ₹40.0
    cfg_per_lot = {"mode": "PER_LOT", "value": 20.0, "enabled": True}
    assert compute_brokerage(cfg_per_lot, price=150.0, lots=2, pnl_qty=130.0) == 40.0

    # PERCENT: 0.05% of full trade value (price=100.0, pnl_qty=65.0 -> trade_val=6500.0 -> 0.05% = ₹3.25)
    cfg_pct = {"mode": "PERCENT", "value": 0.05, "enabled": True}
    assert compute_brokerage(cfg_pct, price=100.0, lots=1, pnl_qty=65.0) == 3.25

    # Disabled config -> 0.0
    cfg_disabled = {"mode": "PER_LOT", "value": 50.0, "enabled": False}
    assert compute_brokerage(cfg_disabled, price=100.0, lots=5, pnl_qty=325.0) == 0.0

    # None config -> 0.0
    assert compute_brokerage(None, price=100.0, lots=5, pnl_qty=325.0) == 0.0


# ---------------------------------------------------------------------------
# 2. 5-Tier Resolution Hierarchy
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resolution_hierarchy():
    db = get_db()
    u_id = "brok_test_user_res"

    # Clean any leftover configs
    await db.brokerage_config.delete_many({"scope": "global", "segment": "future"})
    await db.brokerage_config.delete_many({"user_id": u_id})

    # Tier 5: No config -> None (zero)
    resolved = await resolve_brokerage_config(u_id, "future", "INDEX")
    assert resolved is None

    # Insert Tier 4: Global + Segment ("any")
    await db.brokerage_config.insert_one({
        "scope": "global",
        "segment": "future",
        "instrument_type": "any",
        "mode": "PER_LOT",
        "value": 10.0,
        "enabled": True,
        "test_data": True,
    })
    resolved = await resolve_brokerage_config(u_id, "future", "INDEX")
    assert resolved is not None
    assert resolved["value"] == 10.0

    # Insert Tier 3: Global + Segment + Type ("INDEX")
    await db.brokerage_config.insert_one({
        "scope": "global",
        "segment": "future",
        "instrument_type": "INDEX",
        "mode": "PER_LOT",
        "value": 20.0,
        "enabled": True,
        "test_data": True,
    })
    resolved = await resolve_brokerage_config(u_id, "future", "INDEX")
    assert resolved is not None
    assert resolved["value"] == 20.0
    # But MCX still gets Tier 4
    resolved_mcx = await resolve_brokerage_config(u_id, "future", "MCX")
    assert resolved_mcx is not None
    assert resolved_mcx["value"] == 10.0

    # Insert Tier 2: User + Segment ("any")
    await db.brokerage_config.insert_one({
        "scope": "user",
        "user_id": u_id,
        "segment": "future",
        "instrument_type": "any",
        "mode": "PER_LOT",
        "value": 30.0,
        "enabled": True,
        "test_data": True,
    })
    resolved = await resolve_brokerage_config(u_id, "future", "INDEX")
    assert resolved is not None
    assert resolved["value"] == 30.0

    # Insert Tier 1: User + Segment + Type ("INDEX")
    await db.brokerage_config.insert_one({
        "scope": "user",
        "user_id": u_id,
        "segment": "future",
        "instrument_type": "INDEX",
        "mode": "PER_LOT",
        "value": 40.0,
        "enabled": True,
        "test_data": True,
    })
    resolved = await resolve_brokerage_config(u_id, "future", "INDEX")
    assert resolved is not None
    assert resolved["value"] == 40.0


# ---------------------------------------------------------------------------
# 3. Roundtrip Balance Verification & Accounting Atomicity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_roundtrip_balance_and_accounting():
    db = get_db()
    u_id = "brok_test_user_roundtrip"
    initial_balance = 200000.0

    await db.users.insert_one({
        "user_id": u_id,
        "name": "Roundtrip Trader",
        "balance": initial_balance,
        "available_balance": initial_balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "equity": initial_balance,
        "total_brokerage_paid": 0.0,
        "allowed_segments": ["option", "future"],
        "allowed_instrument_types": ["INDEX"],
    })

    # Set User Brokerage: ₹25 per lot
    await db.brokerage_config.insert_one({
        "scope": "user",
        "user_id": u_id,
        "segment": "option",
        "instrument_type": "INDEX",
        "mode": "PER_LOT",
        "value": 25.0,
        "enabled": True,
        "test_data": True,
    })

    # Contract mock
    contract = {
        "symbol": "NIFTY",
        "tradingsymbol": "NIFTY26SEP24000CE",
        "exchange": "NFO",
        "symboltoken": "99901",
        "lot_size": 50,
        "instrument_type": "INDEX",
    }

    # 1. Open Position: BUY 2 lots @ ₹100. Premium = 2 * 50 * 100 = ₹10,000.
    # Entry Brokerage = 2 lots * ₹25 = ₹50.
    # Total Required = ₹10,050.
    trade = await open_position(
        user_id=u_id,
        segment="option",
        contract=contract,
        action="BUY",
        lots=2,
        qty=100,
        price=100.0,
        source="MARKET",
    )

    user_after_open = await db.users.find_one({"user_id": u_id})
    assert user_after_open["available_balance"] == round(initial_balance - 10050.0, 2)
    assert user_after_open["margin_blocked"] == 10000.0
    assert user_after_open["realized_pnl"] == -50.0
    assert user_after_open["total_brokerage_paid"] == 50.0

    assert trade["entry_brokerage"] == 50.0
    assert trade["brokerage_total"] == 50.0
    assert trade["net_pnl"] == -50.0
    assert trade["pnl"] == 0.0  # GROSS

    # 2. Close Position: Exit @ ₹150.
    # Gross P&L = (150 - 100) * 100 = +₹5,000.
    # Exit Brokerage = 2 lots * ₹25 = ₹50.
    # Net P&L = 5000 - 100 = ₹4,900.
    # Total balance credit on exit = margin_released (10,000) + gross_pnl (5,000) - exit_brokerage (50) = ₹14,950.
    closed_trade = await _close_single_trade(
        segment="option",
        trade=trade,
        exit_price=150.0,
        closed_by=u_id,
    )

    user_after_close = await db.users.find_one({"user_id": u_id})
    expected_available = initial_balance + 5000.0 - 100.0  # initial + gross_pnl - total_brokerage
    assert user_after_close["available_balance"] == round(expected_available, 2)
    assert user_after_close["margin_blocked"] == 0.0
    assert user_after_close["realized_pnl"] == 4900.0  # net realized
    assert user_after_close["total_brokerage_paid"] == 100.0

    assert closed_trade["pnl"] == 5000.0  # GROSS preserved!
    assert closed_trade["exit_brokerage"] == 50.0
    assert closed_trade["brokerage_total"] == 100.0
    assert closed_trade["net_pnl"] == 4900.0


# ---------------------------------------------------------------------------
# 4. Shortfall Error Format
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_shortfall_error_formatting():
    db = get_db()
    u_id = "brok_test_user_shortfall"
    balance = 1000.0

    await db.users.insert_one({
        "user_id": u_id,
        "balance": balance,
        "available_balance": balance,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
    })

    # Brokerage: ₹100/lot
    await db.brokerage_config.insert_one({
        "scope": "user",
        "user_id": u_id,
        "segment": "option",
        "instrument_type": "INDEX",
        "mode": "PER_LOT",
        "value": 100.0,
        "enabled": True,
        "test_data": True,
    })

    contract = {
        "symbol": "NIFTY",
        "tradingsymbol": "NIFTY26SEP24000CE",
        "exchange": "NFO",
        "symboltoken": "99901",
        "lot_size": 50,
        "instrument_type": "INDEX",
    }

    # Margin = 50 * 50 = ₹2,500. Brokerage = ₹100. Total = ₹2,600. Available = ₹1,000. Shortfall = ₹1,600.
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await open_position(
            user_id=u_id,
            segment="option",
            contract=contract,
            action="BUY",
            lots=1,
            qty=50,
            price=50.0,
        )

    err = str(exc_info.value.detail)
    assert "Margin: ₹2,500.00" in err
    assert "Brokerage: ₹100.00" in err
    assert "Total: ₹2,600.00" in err
    assert "Available: ₹1,000.00" in err
    assert "Shortfall: ₹1,600.00" in err


# ---------------------------------------------------------------------------
# 5. Rate Change Immutability
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rate_change_immutability():
    db = get_db()
    u_id = "brok_test_user_immutable"

    await db.users.insert_one({
        "user_id": u_id,
        "balance": 100000.0,
        "available_balance": 100000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
    })

    # Set rate = ₹20
    await db.brokerage_config.insert_one({
        "scope": "user",
        "user_id": u_id,
        "segment": "option",
        "instrument_type": "INDEX",
        "mode": "PER_LOT",
        "value": 20.0,
        "enabled": True,
        "test_data": True,
    })

    contract = {
        "symbol": "NIFTY",
        "tradingsymbol": "NIFTY26SEP24000CE",
        "exchange": "NFO",
        "symboltoken": "99901",
        "lot_size": 50,
        "instrument_type": "INDEX",
    }

    trade = await open_position(
        user_id=u_id,
        segment="option",
        contract=contract,
        action="BUY",
        lots=1,
        qty=50,
        price=10.0,
    )
    assert trade["entry_brokerage"] == 20.0

    # Admin changes the rate afterwards to ₹100
    await db.brokerage_config.update_one(
        {"scope": "user", "user_id": u_id, "segment": "option"},
        {"$set": {"value": 100.0}},
    )

    # Check that trade in DB still has entry_brokerage = 20.0
    stored_trade = await db.trades_option.find_one({"trade_id": trade["trade_id"]})
    assert stored_trade["entry_brokerage"] == 20.0
    assert stored_trade["brokerage_value"] == 20.0


# ---------------------------------------------------------------------------
# 6. Concurrent Close Race Safety
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_close_race_safety():
    db = get_db()
    u_id = "brok_test_user_race"

    await db.users.insert_one({
        "user_id": u_id,
        "balance": 100000.0,
        "available_balance": 100000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
    })

    await db.brokerage_config.insert_one({
        "scope": "user",
        "user_id": u_id,
        "segment": "option",
        "instrument_type": "INDEX",
        "mode": "PER_LOT",
        "value": 20.0,
        "enabled": True,
        "test_data": True,
    })

    contract = {
        "symbol": "NIFTY",
        "tradingsymbol": "NIFTY26SEP24000CE",
        "exchange": "NFO",
        "symboltoken": "99901",
        "lot_size": 50,
        "instrument_type": "INDEX",
    }

    trade = await open_position(
        user_id=u_id,
        segment="option",
        contract=contract,
        action="BUY",
        lots=1,
        qty=50,
        price=10.0,
    )

    # Launch 2 simultaneous closes
    res1, res2 = await asyncio.gather(
        _close_single_trade("option", trade, 15.0, closed_by="CALLER_1"),
        _close_single_trade("option", trade, 15.0, closed_by="CALLER_2"),
    )

    # Exactly one must succeed, one must return None
    winners = [r for r in [res1, res2] if r is not None]
    assert len(winners) == 1

    user_fresh = await db.users.find_one({"user_id": u_id})
    # Total brokerage paid must be exactly 20 (entry) + 20 (exit) = 40. NOT 60!
    assert user_fresh["total_brokerage_paid"] == 40.0


# ---------------------------------------------------------------------------
# 7. Auto Square-Off Charges Exit Brokerage
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_auto_square_off_charges_exit_brokerage():
    db = get_db()
    u_id = "brok_test_user_autosq"

    await db.users.insert_one({
        "user_id": u_id,
        "balance": 100000.0,
        "available_balance": 100000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "total_brokerage_paid": 0.0,
    })

    await db.brokerage_config.insert_one({
        "scope": "user",
        "user_id": u_id,
        "segment": "option",
        "instrument_type": "INDEX",
        "mode": "PER_LOT",
        "value": 15.0,
        "enabled": True,
        "test_data": True,
    })

    contract = {
        "symbol": "NIFTY",
        "tradingsymbol": "NIFTY26SEP24000CE",
        "exchange": "NFO",
        "symboltoken": "99901",
        "lot_size": 50,
        "instrument_type": "INDEX",
    }

    trade = await open_position(
        user_id=u_id,
        segment="option",
        contract=contract,
        action="BUY",
        lots=1,
        qty=50,
        price=10.0,
    )

    closed = await _close_single_trade(
        segment="option",
        trade=trade,
        exit_price=5.0,
        closed_by="SYSTEM_AUTO_SQUARE_OFF",
    )
    assert closed is not None
    assert closed["closed_by"] == "SYSTEM_AUTO_SQUARE_OFF"
    assert closed["exit_brokerage"] == 15.0
    assert closed["brokerage_total"] == 30.0

    user_fresh = await db.users.find_one({"user_id": u_id})
    assert user_fresh["total_brokerage_paid"] == 30.0


# ---------------------------------------------------------------------------
# 8. Admin CRUD Endpoints & Summary Aggregation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_brokerage_crud_and_summary():
    transport = ASGITransport(app=app)
    admin_token = create_access_token("admin", "admin")
    headers = {"Authorization": f"Bearer {admin_token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. PUT global config
        put_res = await ac.put(
            "/admin/brokerage",
            headers=headers,
            json={
                "segment": "future",
                "instrument_type": "MCX",
                "mode": "PERCENT",
                "value": 0.02,
                "enabled": True,
            },
        )
        assert put_res.status_code == 200
        cfg = put_res.json()["config"]
        assert cfg["segment"] == "future"
        assert cfg["instrument_type"] == "MCX"
        assert cfg["mode"] == "PERCENT"
        assert cfg["value"] == 0.02

        # Verify audit log was created
        db = get_db()
        audit = await db.audit_logs.find_one({"action": "SET_GLOBAL_BROKERAGE_CONFIG"})
        assert audit is not None
        assert audit["details"]["after"]["value"] == 0.02

        # 2. GET global configs
        get_res = await ac.get("/admin/brokerage", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["count"] >= 1

        # 3. PUT user override
        target_uid = "brok_test_user_target"
        await db.users.insert_one({"user_id": target_uid, "name": "Target User"})

        user_put_res = await ac.put(
            f"/admin/users/{target_uid}/brokerage",
            headers=headers,
            json={
                "segment": "future",
                "instrument_type": "MCX",
                "mode": "PER_LOT",
                "value": 50.0,
                "enabled": True,
            },
        )
        assert user_put_res.status_code == 200
        user_cfg = user_put_res.json()["config"]
        assert user_cfg["scope"] == "user"
        assert user_cfg["user_id"] == target_uid
        assert user_cfg["value"] == 50.0

        # 4. DELETE user override
        del_res = await ac.delete(
            f"/admin/users/{target_uid}/brokerage?segment=future&instrument_type=MCX",
            headers=headers,
        )
        assert del_res.status_code == 200
        assert del_res.json()["deleted_count"] == 1

        # 5. GET summary
        sum_res = await ac.get("/admin/brokerage/summary", headers=headers)
        assert sum_res.status_code == 200
        summary_data = sum_res.json()
        assert "total_brokerage_collected" in summary_data
        assert "by_segment" in summary_data


# ---------------------------------------------------------------------------
# 9. User Preview and Limit Status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_user_preview_and_limit_status():
    db = get_db()
    u_id = "brok_test_user_preview"
    await db.users.insert_one({
        "user_id": u_id,
        "name": "Preview Trader",
        "balance": 100000.0,
        "available_balance": 99960.0,
        "margin_blocked": 0.0,
        "realized_pnl": -40.0,
        "total_brokerage_paid": 40.0,
        "allowed_segments": ["option", "future"],
        "allowed_instrument_types": ["INDEX"],
    })

    # Set User Brokerage: ₹30/lot for option
    await db.brokerage_config.insert_one({
        "scope": "user",
        "user_id": u_id,
        "segment": "option",
        "instrument_type": "INDEX",
        "mode": "PER_LOT",
        "value": 30.0,
        "enabled": True,
        "test_data": True,
    })

    transport = ASGITransport(app=app)
    user_token = create_access_token(u_id, "user")
    headers = {"Authorization": f"Bearer {user_token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Check limit status includes total_brokerage_paid
        lim_res = await ac.get("/user/limit-status", headers=headers)
        assert lim_res.status_code == 200
        lim_data = lim_res.json()
        assert lim_data["total_brokerage_paid"] == 40.0

        # Check brokerage preview
        prev_res = await ac.get(
            "/user/brokerage-preview?segment=option&instrument=NIFTY&lots=2&price=150",
            headers=headers,
        )
        assert prev_res.status_code == 200
        prev_data = prev_res.json()
        assert prev_data["estimated_brokerage"] == 60.0  # 2 lots * 30
        assert prev_data["mode"] == "PER_LOT"
        assert prev_data["rate"] == 30.0
