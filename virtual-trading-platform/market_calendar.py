"""Market Calendar & Trading Hours Service
Handles Indian Standard Time (Asia/Kolkata) trading sessions, holidays, market hours enforcement,
and contract expiry cutoff evaluations for NSE, BSE, NFO, BFO, and MCX.
"""
import os
import logging
from datetime import datetime, date, time as dtime
from typing import Any, Dict, List, Optional, Union
from zoneinfo import ZoneInfo

logger = logging.getLogger("virtual_trading_platform.market_calendar")

IST = ZoneInfo("Asia/Kolkata")

# Default session configurations (Mon-Fri)
DEFAULT_MARKET_SESSIONS: Dict[str, Dict[str, Any]] = {
    "NSE": {"open": "09:15", "close": "15:30", "days": [0, 1, 2, 3, 4]},
    "NFO": {"open": "09:15", "close": "15:30", "days": [0, 1, 2, 3, 4]},
    "BSE": {"open": "09:15", "close": "15:30", "days": [0, 1, 2, 3, 4]},
    "BFO": {"open": "09:15", "close": "15:30", "days": [0, 1, 2, 3, 4]},
    "MCX": {"open": "09:00", "close": "23:30", "days": [0, 1, 2, 3, 4]},
}

# In-memory cached sessions (updated from DB when available)
_cached_sessions: Dict[str, Dict[str, Any]] = dict(DEFAULT_MARKET_SESSIONS)
_cached_holidays: set = set()


def now_ist() -> datetime:
    """Returns current datetime in Indian Standard Time (Asia/Kolkata)."""
    return datetime.now(IST)


def normalize_exchange(exchange: str) -> str:
    """Normalize exchange and derivative segment codes."""
    exch = (exchange or "").strip().upper()
    if exch in ("NFO", "NSE"):
        return "NSE"
    if exch in ("BFO", "BSE"):
        return "BSE"
    if exch == "MCX":
        return "MCX"
    return exch


def set_cached_sessions(sessions: Dict[str, Dict[str, Any]]) -> None:
    """Update in-memory session settings (e.g. from MongoDB settings doc)."""
    global _cached_sessions
    _cached_sessions.update(sessions)


def set_cached_holidays(holidays: List[str]) -> None:
    """Update in-memory holidays set (format YYYY-MM-DD)."""
    global _cached_holidays
    _cached_holidays = set(holidays)


def get_session_times(exchange: str) -> Dict[str, Any]:
    """Retrieve session open/close times for the given exchange."""
    exch = normalize_exchange(exchange)
    return _cached_sessions.get(exch, DEFAULT_MARKET_SESSIONS.get(exch, {"open": "09:15", "close": "15:30", "days": [0, 1, 2, 3, 4]}))


def parse_time_str(t_str: str) -> dtime:
    """Parse 'HH:MM' string to datetime.time."""
    parts = t_str.strip().split(":")
    return dtime(int(parts[0]), int(parts[1]))


def is_market_open(exchange: str, current_time: Optional[datetime] = None) -> bool:
    """Check if the market for the given exchange is currently open.
    
    Validates:
      1. Day of the week (Mon-Fri by default)
      2. Market holidays (YYYY-MM-DD)
      3. Trading session hours in IST (open_time <= now <= close_time)
    """
    if current_time is None:
        current_time = now_ist()
    elif current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=IST)
    else:
        current_time = current_time.astimezone(IST)

    date_str = current_time.strftime("%Y-%m-%d")
    if date_str in _cached_holidays:
        return False

    session = get_session_times(exchange)
    allowed_days = session.get("days", [0, 1, 2, 3, 4])
    if current_time.weekday() not in allowed_days:
        return False

    open_t = parse_time_str(session.get("open", "09:15"))
    close_t = parse_time_str(session.get("close", "15:30"))

    cur_t = current_time.time()
    return open_t <= cur_t <= close_t


def contract_expired(
    exchange: str,
    expiry_date: Union[str, date, datetime],
    current_time: Optional[datetime] = None,
) -> bool:
    """Returns True once current_time passes the expiry date at that exchange's close time.
    
    For NSE/BSE: expires at 15:30 IST on the expiry date.
    For MCX: expires at 23:30 IST (or configured close) on the expiry date.
    
    If current_time >= expiry cutoff datetime: True (expired)
    Otherwise: False (still active / tradeable)
    """
    if current_time is None:
        current_time = now_ist()
    elif current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=IST)
    else:
        current_time = current_time.astimezone(IST)

    # Resolve target expiry date
    exp_d: date
    if isinstance(expiry_date, str):
        cleaned = expiry_date.strip().upper()
        parsed = False
        for fmt in ("%d%b%Y", "%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y"):
            try:
                exp_d = datetime.strptime(cleaned, fmt).date()
                parsed = True
                break
            except ValueError:
                pass
        if not parsed:
            raise ValueError(f"Unrecognized expiry date format: '{expiry_date}'")
    elif isinstance(expiry_date, datetime):
        exp_d = expiry_date.date()
    elif isinstance(expiry_date, date):
        exp_d = expiry_date
    else:
        raise TypeError(f"Invalid expiry_date type: {type(expiry_date)}")

    session = get_session_times(exchange)
    close_t = parse_time_str(session.get("close", "15:30" if normalize_exchange(exchange) != "MCX" else "23:30"))
    cutoff_dt = datetime.combine(exp_d, close_t, tzinfo=IST)

    return current_time >= cutoff_dt
