"""Pytest configuration and global fixtures.
Ensures tests run deterministically regardless of the developer's execution time of day.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

IST = ZoneInfo("Asia/Kolkata")
# Wednesday 11:00 AM IST (regular active trading hours for both NSE and MCX)
MOCK_MARKET_OPEN_TIME = datetime(2026, 9, 30, 11, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def default_market_open_for_tests(monkeypatch):
    """By default, mock now_ist to a standard weekday trading hour so standard trade tests pass."""
    import market_calendar
    monkeypatch.setattr(market_calendar, "now_ist", lambda: MOCK_MARKET_OPEN_TIME)
