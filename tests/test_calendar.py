"""Offline tests for the persisted trading calendar (calendar.py)."""
import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

import ashare_mcp.data.calendar as cal
from ashare_mcp.config import data_dir


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    cal._reset()
    yield
    cal._reset()


def _stub_fetch(monkeypatch, days, calls=None):
    def fake():
        if calls is not None:
            calls.append(1)
        return pd.DataFrame({"trade_date": days})
    monkeypatch.setattr(cal.ak, "calendar_trade_date_hist_sina", fake)


def _write_file(days, fetched_at=None):
    rec = {"fetched_at": (fetched_at or datetime.now()).isoformat(),
           "days": days}
    (data_dir() / "trade_calendar.json").write_text(
        json.dumps(rec), encoding="utf-8")


# last day must be >= today or every _days() call treats the file as stale
DAYS = ["2025-06-09", "2025-06-10", "2025-06-11", "2030-12-31"]


def test_fetch_writes_file_and_reads(monkeypatch):
    calls = []
    _stub_fetch(monkeypatch, DAYS, calls)
    assert cal.is_trading_day(date(2025, 6, 10)) is True
    assert cal.is_trading_day(date(2025, 6, 8)) is False   # Sun, in range
    assert calls == [1]
    rec = json.loads((data_dir() / "trade_calendar.json").read_text())
    assert rec["days"] == DAYS


def test_fresh_file_used_without_fetch(monkeypatch):
    _write_file(DAYS)
    monkeypatch.setattr(cal.ak, "calendar_trade_date_hist_sina",
                        lambda: (_ for _ in ()).throw(AssertionError("fetch")))
    assert cal.is_trading_day(date(2025, 6, 10)) is True
    assert cal.is_trading_day(date(2025, 6, 8)) is False


def test_stale_file_triggers_refetch(monkeypatch):
    _write_file(["2000-01-03"], fetched_at=datetime.now() - timedelta(days=8))
    calls = []
    _stub_fetch(monkeypatch, DAYS, calls)
    assert cal.is_trading_day(date(2025, 6, 10)) is True
    assert calls == [1]


def test_failed_refetch_uses_stale_file(monkeypatch):
    _write_file(DAYS, fetched_at=datetime.now() - timedelta(days=8))
    def boom():
        raise RuntimeError("offline")
    monkeypatch.setattr(cal.ak, "calendar_trade_date_hist_sina", boom)
    # stale file still answers within its range
    assert cal.is_trading_day(date(2025, 6, 10)) is True
    assert cal.is_trading_day(date(2025, 6, 8)) is False


def test_no_file_and_failure_is_unknown(monkeypatch):
    def boom():
        raise RuntimeError("offline")
    monkeypatch.setattr(cal.ak, "calendar_trade_date_hist_sina", boom)
    assert cal.is_trading_day(date(2025, 6, 10)) is None


def test_beyond_last_day_triggers_refetch(monkeypatch):
    # fresh file whose horizon is before the queried date
    _write_file(["2025-06-09", "2030-01-01"])
    calls = []
    _stub_fetch(monkeypatch, ["2025-06-09", "2030-01-01", "2030-06-03"], calls)
    assert cal.is_trading_day(date(2030, 6, 3)) is True
    assert calls == [1]


def test_beyond_last_day_failed_refetch_unknown(monkeypatch):
    _write_file(["2025-06-09", "2030-01-01"])
    def boom():
        raise RuntimeError("offline")
    monkeypatch.setattr(cal.ak, "calendar_trade_date_hist_sina", boom)
    assert cal.is_trading_day(date(2030, 6, 3)) is None


def test_refetch_throttled_beyond_horizon(monkeypatch):
    """Two consecutive beyond-horizon queries trigger at most one fetch."""
    _write_file(["2025-06-09", "2030-01-01"])
    calls = []
    _stub_fetch(monkeypatch, ["2025-06-09", "2030-01-01", "2030-06-03"], calls)
    assert cal.is_trading_day(date(2030, 6, 3)) is True   # refetch #1
    # still beyond the new horizon, but throttled -> unknown, no 2nd fetch
    assert cal.is_trading_day(date(2030, 9, 1)) is None
    assert calls == [1]


def test_refetch_throttled_when_offline(monkeypatch):
    """Failing fetches are throttled too: two calls, one attempt."""
    _write_file(DAYS, fetched_at=datetime.now() - timedelta(days=8))
    calls = []
    def boom():
        calls.append(1)
        raise RuntimeError("offline")
    monkeypatch.setattr(cal.ak, "calendar_trade_date_hist_sina", boom)
    cal._reset()
    assert cal.is_trading_day(date(2025, 6, 10)) is True   # stale file
    assert cal.is_trading_day(date(2025, 6, 10)) is True
    assert calls == [1]

