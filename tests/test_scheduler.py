"""Offline tests for calendar-aware scheduler behaviour."""
from datetime import datetime

import pytest

from ashare_mcp.data import calendar as cal
from ashare_mcp.web import scheduler


@pytest.fixture(autouse=True)
def _state():
    saved = dict(scheduler._state)
    yield
    scheduler._state.clear()
    scheduler._state.update(saved)


def test_in_session_weekday_holiday(monkeypatch):
    """A weekday the calendar marks as a holiday is out of session."""
    monkeypatch.setattr(cal, "is_trading_day", lambda d: False)
    monday_10am = datetime(2025, 6, 9, 10, 0)
    assert scheduler._in_session(monday_10am) is False


def test_in_session_unknown_falls_back_to_weekday_rule(monkeypatch):
    monkeypatch.setattr(cal, "is_trading_day", lambda d: None)
    assert scheduler._in_session(datetime(2025, 6, 9, 10, 0)) is True   # Mon
    assert scheduler._in_session(datetime(2025, 6, 9, 12, 0)) is False  # lunch
    assert scheduler._in_session(datetime(2025, 6, 9, 14, 0)) is True


def test_settle_tick_skips_holiday_without_marking(monkeypatch):
    monkeypatch.setattr(cal, "is_trading_day", lambda d: False)
    scheduler._state["last_settlement_date"] = None
    res = scheduler.settle_tick()
    assert res == {"skipped": "holiday"}
    assert scheduler._state["last_settlement_date"] is None
