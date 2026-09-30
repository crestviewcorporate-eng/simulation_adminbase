import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from db import get_db
from trade_engine import resolve_contract, compute_required_lock, open_position
from fastapi import HTTPException


@pytest.fixture(autouse=True)
async def cleanup_te_db():
    db = get_db()
    test_user_id = "te_unit_test_user"
    await db.users.delete_many({"user_id": test_user_id})
    for seg in ("option", "future", "cash"):
        await db[f"trades_{seg}"].delete_many({"user_id": test_user_id})
    yield
    await db.users.delete_many({"user_id": test_user_id})
    for seg in ("option", "future", "cash"):
        await db[f"trades_{seg}"].delete_many({"user_id": test_user_id})


@pytest.mark.asyncio
async def test_resolve_contract_option_and_future():
    # Option resolve
    opt_contract = await resolve_contract(
        segment="option",
        symbol="NIFTY",
        strike=22500.0,
        option_type="CE",
    )
    assert opt_contract is not None
    assert opt_contract["symbol"] == "NIFTY"
    assert opt_contract["option_type"] == "CE"

    # Future resolve
    fut_contract = await resolve_contract(
        segment="future",
        symbol="NIFTY",
    )
    assert fut_contract is not None
    assert fut_contract["segment"] == "future"

    # Nonexistent contract raises 404
    with pytest.raises(HTTPException) as exc_info:
        await resolve_contract(segment="option", symbol="NONEXISTENT_SYMBOL")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_compute_required_lock_future_and_option():
    db = get_db()
    await db.instrument_margins.update_one(
        {"symbol": "NIFTY", "segment": "future"},
        {"$set": {"symbol": "NIFTY", "segment": "future", "margin_required": 75000.0}},
        upsert=True,
    )

    fut_contract = {"symbol": "NIFTY", "lot_size": 25, "segment": "future"}
    lock_fut = await compute_required_lock(
        segment="future",
        contract=fut_contract,
        price=22000.0,
        lots=2,
    )
    assert lock_fut == 150000.0  # 2 * 75,000

    opt_contract = {"symbol": "NIFTY", "lot_size": 25, "segment": "option"}
    lock_opt = await compute_required_lock(
        segment="option",
        contract=opt_contract,
        price=120.0,
        lots=2,
    )
    assert lock_opt == 6000.0  # 120 * 50


@pytest.mark.asyncio
async def test_open_position_atomic_balance_lock():
    db = get_db()
    user_id = "te_unit_test_user"
    now = datetime.now(timezone.utc)

    await db.users.insert_one({
        "user_id": user_id,
        "name": "TE Unit User",
        "balance": 50000.0,
        "available_balance": 50000.0,
        "margin_blocked": 0.0,
        "realized_pnl": 0.0,
        "created_at": now,
        "updated_at": now,
    })

    opt_contract = {
        "symbol": "NIFTY",
        "tradingsymbol": "NIFTY26MAR22500CE",
        "exchange": "NFO",
        "symboltoken": "1001",
        "lot_size": 50,
        "segment": "option",
    }

    trade = await open_position(
        user_id=user_id,
        segment="option",
        contract=opt_contract,
        action="BUY",
        lots=1,
        qty=50,
        price=100.0,
        source="MARKET",
    )

    assert trade["status"] == "OPEN"
    assert trade["margin_blocked_amount"] == 5000.0
    assert trade["source"] == "MARKET"

    user_doc = await db.users.find_one({"user_id": user_id})
    assert user_doc["available_balance"] == 45000.0
    assert user_doc["margin_blocked"] == 5000.0
