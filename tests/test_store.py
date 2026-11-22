"""Offline tests for the SQLite daily-bar store (stub fetch, fake clock)."""
from datetime import datetime, timedelta

import pandas as pd
import pytest

import ashare_mcp.data.store as store


class FakeClock:
    """Controllable store._now replacement (CST fixed)."""

    def __init__(self, dt: datetime):
        self.dt = dt

    def set(self, dt: datetime):
        self.dt = dt


@pytest.fixture
def clock(monkeypatch):
    # start: a trading Tuesday 2025-06-10 16:00 CST (post-settle)
    c = FakeClock(datetime(2025, 6, 10, 16, 0, tzinfo=store._TZ))
    monkeypatch.setattr(store, "_now", lambda: c.dt)
    return c


def _bars(start: str, days: int, close0: float = 10.0) -> pd.DataFrame:
    d0 = pd.Timestamp(start)
    return pd.DataFrame([{
        "date": (d0 + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
        "open": close0, "high": close0 + 1, "low": close0 - 1,
        "close": close0 + i * 0.1, "volume": 1e6, "amount": 1e7,
        "amplitude": 2.0, "pct_chg": 1.0, "change": 0.1, "turnover": 1.5,
    } for i in range(days)])


def test_first_call_full_fetches_and_persists(clock):
    calls = []
    def fetch(s, e):
        calls.append((s, e))
        return _bars("2025-06-01", 10)
    df = store.get_daily("600519", "qfq", "2025-06-01", "2025-06-10", fetch)
    assert len(calls) == 1 and calls[0] == ("20250601", "20250610")
    assert len(df) == 10
    meta = store._meta("600519", "qfq")
    assert meta["first_date"] == "2025-06-01" and meta["last_date"] == "2025-06-10"


def test_fresh_within_cutoff_no_fetch(clock):
    calls = []
    def fetch(s, e):
        calls.append(1)
        return _bars("2025-06-01", 10)
    store.get_daily("600519", "qfq", "2025-06-01", "2025-06-10", fetch)
    n = len(calls)
    df = store.get_daily("600519", "qfq", "2025-06-03", "2025-06-10", fetch)
    assert len(calls) == n  # still 1 — 16:00 > 15:30 cutoff, meta fresh
    assert len(df) == 8


def test_stale_incremental_start(clock):
    calls = []
    def fetch(s, e):
        calls.append(s)
        return _bars("2025-06-01", 12)
    store.get_daily("600519", "qfq", "2025-06-01", "2025-06-10", fetch)
    # move to next day morning (before settle) -> stale
    clock.set(datetime(2025, 6, 11, 16, 0, tzinfo=store._TZ))
    calls.clear()
    df = store.get_daily("600519", "qfq", "2025-06-01", "2025-06-11", fetch)
    # last persisted = 2025-06-10; incremental starts last_date - 10d
    assert calls == ["20250531"]
    assert len(df) == 11  # 10 stored + today's live bar


def test_qfq_mismatch_triggers_refetch(clock):
    seq = [_bars("2025-06-01", 10),
           _bars("2025-06-03", 12, close0=20.0),
           _bars("2025-06-01", 12, close0=20.0)]
    calls = []
    def fetch(s, e):
        calls.append(s)
        return seq.pop(0)
    store.get_daily("600519", "qfq", "2025-06-01", "2025-06-10", fetch)
    clock.set(datetime(2025, 6, 11, 16, 0, tzinfo=store._TZ))
    df = store.get_daily("600519", "qfq", "2025-06-01", "2025-06-11", fetch)
    assert calls == ["20250601", "20250531", "20250601"]
    assert df["close"].iloc[0] == 20.0


def test_today_bar_not_persisted_but_returned(clock):
    clock.set(datetime(2025, 6, 10, 10, 0, tzinfo=store._TZ))  # intraday
    def fetch(s, e):
        return _bars("2025-06-01", 10)
    df = store.get_daily("600519", "qfq", "2025-06-01", "2025-06-10", fetch)
    assert len(df) == 10 and df["date"].iloc[-1] == "2025-06-10"
    meta = store._meta("600519", "qfq")
    assert meta["last_date"] == "2025-06-09"  # today's bar not stored


def test_fetch_failure_returns_stale(clock):
    store.get_daily("600519", "qfq", "2025-06-01", "2025-06-10",
                    lambda s, e: _bars("2025-06-01", 10))
    clock.set(datetime(2025, 6, 11, 16, 0, tzinfo=store._TZ))
    def boom(s, e):
        raise RuntimeError("net down")
    df = store.get_daily("600519", "qfq", "2025-06-01", "2025-06-10", boom)
    assert len(df) == 10  # all 10 bars settled at 16:00 and persisted


def test_fetch_failure_empty_raises(clock):
    def boom(s, e):
        raise RuntimeError("net down")
    with pytest.raises(RuntimeError, match="net down"):
        store.get_daily("600519", "qfq", "2025-06-01", "2025-06-10", boom)


def test_store_disabled_passthrough(clock, monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_STORE", "0")
    calls = []
    def fetch(s, e):
        calls.append((s, e))
        return _bars("2025-06-01", 10)
    df = store.get_daily("600519", "qfq", "2025-06-01", "2025-06-05", fetch)
    assert len(calls) == 1 and len(df) == 5
    assert store._meta("600519", "qfq") is None
