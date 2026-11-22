"""Local SQLite store for daily bars — a disposable cache, not source of truth.

Layout: ``data_dir()/market.db``, WAL mode, one connection per operation.
``ASHARE_MCP_STORE=0`` disables the store (pass-through to network).

get_daily() implements lazy incremental sync:
- meta fresh iff synced_at >= last settlement cutoff (15:30 Asia/Shanghai)
- stale -> incremental fetch of the last ~10 days; for adjusted series a
  close mismatch on overlapping dates means the adjustment basis changed
  (ex-dividend) -> full refetch.
- only *settled* bars are persisted (today's bar before 15:30 is returned
  but not stored).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Callable

import pandas as pd

from ..config import data_dir

log = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # tzdata missing on Windows etc.
    _TZ = timezone(timedelta(hours=8))

_SETTLE = dtime(15, 30)
_AFTER_SETTLE = dtime(15, 35)
_OVERLAP_DAYS = 10
_MISMATCH_TOL = 0.0005  # 0.05%

_COLS = ["open", "high", "low", "close", "volume", "amount",
         "amplitude", "pct_chg", "change", "turnover"]

_DDL = """
CREATE TABLE IF NOT EXISTS daily_bars(
  key TEXT, adjust TEXT, date TEXT,
  open REAL, high REAL, low REAL, close REAL,
  volume REAL, amount REAL, amplitude REAL,
  pct_chg REAL, change REAL, turnover REAL,
  PRIMARY KEY(key, adjust, date));
CREATE TABLE IF NOT EXISTS sync_meta(
  key TEXT, adjust TEXT, first_date TEXT, last_date TEXT,
  synced_at TEXT, PRIMARY KEY(key, adjust));
"""


def _now() -> datetime:
    return datetime.now(_TZ)


def _db_path():
    return data_dir() / "market.db"


def enabled() -> bool:
    return os.environ.get("ASHARE_MCP_STORE", "1").strip() != "0"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_DDL)
    return conn


def _today() -> str:
    return _now().date().isoformat()


def _settle_cutoff() -> datetime:
    """Last settlement instant: today 15:30, else yesterday 15:30."""
    now = _now()
    day = now.date()
    if now.time() < _SETTLE:
        day = day - timedelta(days=1)
    return datetime.combine(day, _SETTLE, tzinfo=_TZ)


def _intraday() -> bool:
    now = _now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= _SETTLE


def _settled(bar_date: str, today: str) -> bool:
    return bar_date < today or (bar_date == today and _now().time() >= _SETTLE)


def _meta(key: str, adjust: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT first_date, last_date, synced_at FROM sync_meta "
            "WHERE key=? AND adjust=?", (key, adjust)).fetchone()
    if not row:
        return None
    return {"first_date": row[0], "last_date": row[1], "synced_at": row[2]}


def _stored(key: str, adjust: str, start: str, end: str) -> pd.DataFrame:
    with _conn() as c:
        rows = c.execute(
            f"SELECT date,{','.join(_COLS)} FROM daily_bars "
            "WHERE key=? AND adjust=? AND date>=? AND date<=? ORDER BY date",
            (key, adjust, start, end)).fetchall()
    df = pd.DataFrame(rows, columns=["date", *_COLS])
    return df


def _persist(key: str, adjust: str, df: pd.DataFrame, today: str) -> tuple[str | None, str | None]:
    """Upsert settled rows; return (min, max) of persisted dates."""
    df = df[df["date"].map(lambda d: _settled(d, today))]
    if df.empty:
        return None, None
    df = df.reindex(columns=["date", *_COLS])
    with _conn() as c:
        c.executemany(
            f"INSERT OR REPLACE INTO daily_bars VALUES (?,?,?,{','.join('?' * 10)})",
            [(key, adjust, r["date"],
              *[None if pd.isna(r[k]) else float(r[k]) for k in _COLS])
             for _, r in df.iterrows()])
        mn, mx = df["date"].min(), df["date"].max()
        prev = c.execute(
            "SELECT first_date, last_date FROM sync_meta WHERE key=? AND adjust=?",
            (key, adjust)).fetchone()
        first = min(mn, prev[0]) if prev and prev[0] else mn
        last = max(mx, prev[1]) if prev and prev[1] else mx
        c.execute(
            "INSERT OR REPLACE INTO sync_meta VALUES (?,?,?,?,?)",
            (key, adjust, first, last, _now().isoformat()))
        return first, last


def _clear(key: str, adjust: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM daily_bars WHERE key=? AND adjust=?", (key, adjust))
        c.execute("DELETE FROM sync_meta WHERE key=? AND adjust=?", (key, adjust))


def _fix_pct_chg(key: str, adjust: str, df: pd.DataFrame) -> pd.DataFrame:
    """Incremental fetch slices lose the first bar's pct_chg (NaN) — recompute
    from the previous stored close."""
    if "pct_chg" not in df.columns:
        return df
    nan_dates = df.loc[df["pct_chg"].isna(), "date"].tolist()
    if not nan_dates:
        return df
    with _conn() as c:
        for d in nan_dates:
            prev = c.execute(
                "SELECT close FROM daily_bars WHERE key=? AND adjust=? AND date<? "
                "ORDER BY date DESC LIMIT 1", (key, adjust, d)).fetchone()
            if prev and prev[0]:
                close = df.loc[df["date"] == d, "close"].iloc[0]
                df.loc[df["date"] == d, "pct_chg"] = (close / prev[0] - 1) * 100
    return df


def _adjusted_mismatch(key: str, adjust: str, fetched: pd.DataFrame) -> bool:
    """qfq/hfq: stored close vs fetched close on overlapping dates."""
    if adjust in ("", "idx") or fetched.empty:
        return False
    stored = _stored(key, adjust, fetched["date"].min(), fetched["date"].max())
    if stored.empty:
        return False
    m = stored.merge(fetched[["date", "close"]], on="date", suffixes=("_s", "_f"))
    m = m.dropna()
    if m.empty:
        return False
    rel = (m["close_f"] / m["close_s"] - 1).abs()
    return bool((rel > _MISMATCH_TOL).any())


def get_daily(key: str, adjust: str, start: str, end: str,
              fetch: Callable[[str, str], pd.DataFrame]) -> pd.DataFrame:
    """Return daily bars for ``key`` in [start, end] (ISO dates).

    ``fetch(sd_yyyymmdd, ed_yyyymmdd)`` must return an already
    daily-normalized DataFrame (``_norm_kline(df, "daily")`` output).
    """
    if not enabled():
        df = fetch(start.replace("-", ""), end.replace("-", ""))
        return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)

    today = _today()
    meta = _meta(key, adjust)
    cutoff = _settle_cutoff()
    fresh = (meta is not None
             and meta["synced_at"] >= cutoff.isoformat()
             and start >= meta["first_date"])
    live_today: pd.DataFrame | None = None

    try:
        if meta is None or start < meta["first_date"]:
            sd = start if meta is None else min(start, meta["first_date"])
            df = fetch(sd.replace("-", ""), today.replace("-", ""))
            if not df.empty:
                df = _fix_pct_chg(key, adjust, df)
                _persist(key, adjust, df, today)
                live_today = df[df["date"] >= today]
            # the fetch covered [sd, today]: claim coverage from the
            # requested start even when the first bar is later (non-trading
            # days / listing date), so a repeat request stays fresh
            with _conn() as c:
                c.execute(
                    "UPDATE sync_meta SET first_date = MIN(first_date, ?) "
                    "WHERE key=? AND adjust=?", (start, key, adjust))
        elif not fresh:
            sd = (pd.Timestamp(meta["last_date"]) - pd.Timedelta(days=_OVERLAP_DAYS)).strftime("%Y%m%d")
            df = fetch(sd, today.replace("-", ""))
            if _adjusted_mismatch(key, adjust, df):
                log.info("adjust basis changed for %s/%s — full refetch", key, adjust)
                _clear(key, adjust)
                df = fetch(meta["first_date"].replace("-", ""), today.replace("-", ""))
            if not df.empty:
                df = _fix_pct_chg(key, adjust, df)
                _persist(key, adjust, df, today)
                live_today = df[df["date"] >= today]
        elif _intraday() and end >= today:
            tail = fetch(
                (pd.Timestamp(today) - pd.Timedelta(days=5)).strftime("%Y%m%d"),
                today.replace("-", ""))
            if not tail.empty:
                live_today = tail[tail["date"] > meta["last_date"]]
    except Exception:
        stored = _stored(key, adjust, start, end)
        if stored.empty:
            raise
        log.warning("fetch failed for %s/%s — returning %d stale rows",
                    key, adjust, len(stored), exc_info=True)
        return stored.reset_index(drop=True)

    out = _stored(key, adjust, start, end)
    if live_today is not None and not live_today.empty:
        keep = [d for d in live_today["date"] if start <= d <= end and d not in set(out["date"])]
        if keep:
            out = pd.concat([out, live_today[live_today["date"].isin(keep)]],
                            ignore_index=True)
    return out.sort_values("date").reset_index(drop=True)
