import pytest
from datetime import datetime, timezone
from fastapi import HTTPException
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
    get_current_admin,
    get_current_user,
)
from models import (
    UserCreate,
    UserOut,
    TradeOptionCreate,
    TradeFutureCreate,
    TradeCashCreate,
    TradeOut,
    LimitIncrease,
    SegmentUpdate,
)


def test_password_hashing():
    raw_pass = "SecurePass123!"
    hashed = hash_password(raw_pass)
    assert hashed != raw_pass
    assert verify_password(raw_pass, hashed) is True
    assert verify_password("WrongPass", hashed) is False


def test_jwt_token_generation_and_decoding():
    token = create_access_token(user_id="trader01", role="user")
    payload = decode_token(token)
    assert payload["user_id"] == "trader01"
    assert payload["sub"] == "trader01"
    assert payload["role"] == "user"
    assert "exp" in payload


@pytest.mark.asyncio
async def test_role_dependencies():
    user_token = create_access_token(user_id="trader_xyz", role="user")
    admin_token = create_access_token(user_id="admin_master", role="admin")

    user_payload = decode_token(user_token)
    admin_payload = decode_token(admin_token)

    # Valid user
    assert await get_current_user(user_payload) == "trader_xyz"

    # Valid admin
    assert await get_current_admin(admin_payload) == "admin_master"

    # User accessing admin role -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        await get_current_admin(user_payload)
    assert exc_info.value.status_code == 403

    # Admin accessing user role -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(admin_payload)
    assert exc_info.value.status_code == 403


def test_pydantic_models():
    user = UserCreate(
        user_id="trader99",
        password="password123",
        name="Hariom Singh",
        allowed_segments=["option", "future"],
        trade_limit={"option": 20, "future": 10, "cash": 0},
    )
    assert user.user_id == "trader99"

    user_out = UserOut(
        user_id=user.user_id,
        name=user.name,
        allowed_segments=user.allowed_segments,
        trade_limit=user.trade_limit,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    assert not hasattr(user_out, "password")
    assert not hasattr(user_out, "password_hash")

    option_trade = TradeOptionCreate(
        instrument="NIFTY",
        expiry="28MAR2026",
        strike=22500,
        option_type="CE",
        action="BUY",
        qty=50,
    )
    assert option_trade.strike == 22500

    future_trade = TradeFutureCreate(
        instrument="BANKNIFTY",
        expiry="28MAR2026",
        action="SELL",
        qty=15,
    )
    assert future_trade.instrument == "BANKNIFTY"

    cash_trade = TradeCashCreate(
        instrument="RELIANCE",
        action="BUY",
        qty=100,
    )
    assert cash_trade.qty == 100
