from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class SegmentType(str, Enum):
    OPTION = "option"
    FUTURE = "future"
    CASH = "cash"


class TradeAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Authentication Schemas
# ---------------------------------------------------------------------------
class AdminLogin(BaseModel):
    username: str = Field(..., description="Admin username")
    password: str = Field(..., min_length=4, description="Admin password")


class UserLogin(BaseModel):
    user_id: str = Field(..., description="Unique User ID")
    password: str = Field(..., min_length=4, description="User password")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    expires_in_hours: int = 8


# ---------------------------------------------------------------------------
# Margin & Balance Management Schemas
# ---------------------------------------------------------------------------
class InstrumentMargin(BaseModel):
    symbol: str
    segment: Literal["option", "future", "cash"]
    margin_required: float = Field(..., ge=0, description="Margin per lot to open one trade")


class BalanceSet(BaseModel):
    balance: float = Field(..., ge=0, description="Sets the user's allocated balance to this exact value")


class BalanceAdd(BaseModel):
    amount: float = Field(..., description="Amount to add to (or subtract from, if negative) the user's current balance")


class MarginUpdate(BaseModel):
    margin_required: float = Field(..., ge=0)


# ---------------------------------------------------------------------------
# User Management Schemas
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    user_id: str = Field(..., min_length=3, max_length=50, description="Unique User ID")
    password: str = Field(..., min_length=6, description="Initial plain text password")
    name: str = Field(..., min_length=1, max_length=100, description="User's full name")
    allowed_segments: List[str] = Field(
        default=["option", "future", "cash"],
        description="List of permitted segments: ['option', 'future', 'cash']"
    )
    allowed_instrument_types: List[str] = Field(
        default=["INDEX"],
        description="List of permitted instrument types: ['INDEX', 'MCX']"
    )
    trade_limit: Optional[Dict[str, int]] = None
    # Balance & Margin fields
    balance: float = 0.0            # allocated capital, admin-set, doesn't change except by admin action
    available_balance: float = 0.0  # balance - margin_blocked + realized_pnl
    margin_blocked: float = 0.0     # sum of margin currently locked in open trades
    realized_pnl: float = 0.0       # cumulative pnl from closed trades
    unrealized_pnl: float = 0.0     # live, recomputed by background engine, cached here
    equity: float = 0.0             # balance + realized_pnl + unrealized_pnl, cached
    loss_pct: float = 0.0           # cached, recomputed by background engine
    auto_square_off_pct: float = 80.0  # threshold, admin can override per user
    last_auto_square_off_at: Optional[datetime] = None
    risk_level: Optional[str] = "normal"
    mtm_stale: bool = False
    mtm_updated_at: Optional[datetime] = None
    total_brokerage_paid: float = 0.0


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    name: str = ""
    allowed_segments: List[str]
    allowed_instrument_types: List[str] = ["INDEX"]
    trade_limit: Optional[Dict[str, int]] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Balance & Margin fields
    balance: float = 0.0            # allocated capital, admin-set, doesn't change except by admin action
    available_balance: float = 0.0  # balance - margin_blocked + realized_pnl
    margin_blocked: float = 0.0     # sum of margin currently locked in open trades
    realized_pnl: float = 0.0       # cumulative pnl from closed trades
    unrealized_pnl: float = 0.0     # live, recomputed by background engine, cached here
    equity: float = 0.0             # balance + realized_pnl + unrealized_pnl, cached
    loss_pct: float = 0.0           # cached, recomputed by background engine
    auto_square_off_pct: float = 80.0  # threshold, admin can override per user
    last_auto_square_off_at: Optional[datetime] = None
    risk_level: Optional[str] = "normal"
    mtm_stale: bool = False
    mtm_updated_at: Optional[datetime] = None
    total_brokerage_paid: float = 0.0
    pending_orders_count: Optional[int] = 0
    pending_reserved: Optional[float] = 0.0


class PasswordReset(BaseModel):
    """Admin resets a user's password directly (optional custom password)."""
    new_password: Optional[str] = Field(default=None, description="Optional custom password, auto-generated if omitted")


class PasswordChange(BaseModel):
    """User changes their own password by verifying current old password."""
    old_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(..., min_length=6, description="New password")


class SegmentUpdate(BaseModel):
    allowed_segments: List[str] = Field(
        ...,
        description="Updated list of permitted segments: e.g. ['option', 'future']"
    )


class InstrumentTypesUpdate(BaseModel):
    allowed_instrument_types: List[str] = Field(
        ...,
        description="Updated list of permitted instrument types: e.g. ['INDEX', 'MCX']"
    )


class LimitIncrease(BaseModel):
    """Deprecated quota model retained for backwards test compatibility."""
    segment: Optional[str] = None
    new_limit: Optional[int] = None


# ---------------------------------------------------------------------------
# Trading Schemas
# ---------------------------------------------------------------------------
class TradeOptionCreate(BaseModel):
    instrument: str = Field(..., description="Underlying index/symbol e.g. NIFTY, BANKNIFTY, SENSEX")
    expiry: Optional[str] = Field(default=None, description="Expiry date e.g. 29SEP2026 (defaults to running expiry)")
    strike: Optional[float] = Field(default=None, gt=0, description="Strike price e.g. 23400 (defaults to nearest ATM)")
    option_type: Literal["CE", "PE"] = Field(..., description="CE for Call, PE for Put")
    action: Literal["BUY", "SELL"] = Field(..., description="BUY or SELL")
    qty: Optional[int] = Field(default=None, gt=0, description="Explicit quantity to trade")
    lots: Optional[int] = Field(default=1, gt=0, description="Number of lots (defaults to 1 if qty not provided)")


class TradeFutureCreate(BaseModel):
    instrument: str = Field(..., description="Underlying index/symbol e.g. NIFTY, BANKNIFTY, SENSEX, GOLD, CRUDEOIL")
    expiry: Optional[str] = Field(default=None, description="Expiry date e.g. 29SEP2026 (defaults to running expiry)")
    action: Literal["BUY", "SELL"] = Field(..., description="BUY or SELL")
    qty: Optional[int] = Field(default=None, gt=0, description="Explicit quantity to trade")
    lots: Optional[int] = Field(default=1, gt=0, description="Number of lots (defaults to 1 if qty not provided)")


class TradeCashCreate(BaseModel):
    instrument: str = Field(..., description="Stock or spot index symbol e.g. NIFTY, BANKNIFTY, SENSEX, RELIANCE")
    action: Literal["BUY", "SELL"] = Field(..., description="BUY or SELL")
    qty: int = Field(..., gt=0, description="Number of shares")


class TradeClose(BaseModel):
    trade_id: str = Field(..., description="ID of open trade to square off / close")


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trade_id: str
    user_id: str
    segment: str  # "option", "future", "cash"
    instrument: str
    action: str  # "BUY", "SELL"
    qty: int
    entry_price: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    status: str = "OPEN"  # "OPEN", "CLOSED", "CANCELLED"
    pnl: float = 0.0
    lot_size: Optional[int] = 1
    margin_blocked_amount: float = 0.0  # margin locked for THIS specific trade
    # Optional segment-specific details
    expiry: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    needs_settlement: Optional[bool] = False
    instrument_type: Optional[str] = "INDEX"
    pnl_qty: Optional[float] = None
    pnl_multiplier_per_lot: Optional[float] = None
    # Brokerage fields
    entry_brokerage: Optional[float] = 0.0
    exit_brokerage: Optional[float] = None
    brokerage_mode: Optional[str] = None
    brokerage_value: Optional[float] = 0.0
    brokerage_total: Optional[float] = 0.0
    net_pnl: Optional[float] = 0.0
    product: Optional[str] = "CF"


# ---------------------------------------------------------------------------
# Brokerage Configuration Schemas
# ---------------------------------------------------------------------------
class BrokerageConfigItem(BaseModel):
    scope: Literal["global", "user"] = "global"
    user_id: Optional[str] = None
    segment: Literal["option", "future", "cash"]
    instrument_type: Literal["INDEX", "MCX", "any"] = "any"
    mode: Literal["PER_LOT", "PERCENT"]
    value: float = Field(..., ge=0)
    enabled: bool = True
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None


class BrokerageConfigCreate(BaseModel):
    segment: Literal["option", "future", "cash"]
    instrument_type: Literal["INDEX", "MCX", "any"] = "any"
    mode: Literal["PER_LOT", "PERCENT"]
    value: float = Field(..., ge=0)
    enabled: bool = True


class BrokeragePreviewOut(BaseModel):
    segment: str
    instrument: str
    instrument_type: str
    mode: str
    rate: float
    estimated_brokerage: float
    contract_value: float


# ---------------------------------------------------------------------------
# Order Schemas (Pending / Limit Orders)
# ---------------------------------------------------------------------------
class OrderCreate(BaseModel):
    instrument: str
    action: Literal["BUY", "SELL"]
    limit_price: float = Field(..., gt=0, description="Target limit price")
    lots: Optional[int] = Field(default=1, ge=1)
    qty: Optional[int] = Field(default=None, ge=1)
    expiry: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    product: Optional[str] = "CF"


class OrderModify(BaseModel):
    limit_price: Optional[float] = Field(default=None, gt=0)
    lots: Optional[int] = Field(default=None, ge=1)
    qty: Optional[int] = Field(default=None, ge=1)


class OrderOut(BaseModel):
    order_id: str
    user_id: str
    segment: str
    instrument_type: str
    instrument: str
    tradingsymbol: str
    exchange: str
    symboltoken: str
    expiry: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    lot_size: int
    lots: int
    qty: int
    pnl_qty: float
    action: str
    order_type: str = "LIMIT"
    limit_price: float
    status: str  # "PENDING", "MODIFYING", "EXECUTED", "CANCELLED", "REJECTED"
    reserved_total: float
    reserved_lock: Optional[float] = 0.0
    reserved_brokerage: Optional[float] = 0.0
    version: int = 1
    created_at: datetime
    modified_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    executed_price: Optional[float] = None
    trade_id: Optional[str] = None
    reject_reason: Optional[str] = None
    cancelled_by: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = []
    product: Optional[str] = "CF"

