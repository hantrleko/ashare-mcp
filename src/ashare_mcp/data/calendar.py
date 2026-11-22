"""A-share trading calendar via akshare (sina), persisted to
<data_dir>/trade_calendar.json as {"fetched_at": iso, "days": [...]}.

is_trading_day(d) -> True / False / None (unknown when no file and no
network). Refetches when the file is missing, fetched_at is older than
7 days, or the queried date is past the last day on file; a failed
refetch falls back to the stale file.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak

from ..config import data_dir

log = logging.getLogger(__name__)

_CN = ZoneInfo("Asia/Shanghai")
_STALE_AFTER = timedelta(days=7)
_FETCH_THROTTLE_S = 3600  # at most one fetch attempt per hour
_PATH = "trade_calendar.json"

_cache: dict[str, Any] | None = None
_last_attempt: float = 0.0


def _cn_now() -> datetime:
    """China wall-clock time as a naive datetime (matches stored ISO)."""
    return datetime.now(_CN).replace(tzinfo=None)


def _load_file() -> dict[str, Any] | None:
    p = data_dir() / _PATH
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d.get("days"), list):
            return d
    except Exception:
        pass
    return None


def _fetch() -> dict[str, Any]:
    global _last_attempt
    _last_attempt = time.time()
    df = ak.calendar_trade_date_hist_sina()
    days = sorted(str(d)[:10] for d in df["trade_date"].tolist())
    rec = {"fetched_at": _cn_now().isoformat(timespec="seconds"),
           "days": days}
    try:
        (data_dir() / _PATH).write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        log.warning("cannot persist trading calendar: %s", e)
    return rec


def _fetch_throttled() -> dict[str, Any] | None:
    """One fetch attempt per hour, success or failure. None on skip/fail."""
    global _last_attempt
    if time.time() - _last_attempt < _FETCH_THROTTLE_S:
        return None
    try:
        return _fetch()
    except Exception as e:
        log.warning("trading calendar fetch failed: %s", e)
        return None


def _days() -> list[str] | None:
    """Return the day list, refetching when needed. None when unknown."""
    global _cache
    rec = _cache if _cache is not None else _load_file()
    stale = (
        rec is None
        or not rec.get("days")
        or _parse_iso(rec.get("fetched_at")) is None
        or _cn_now() - _parse_iso(rec["fetched_at"]) > _STALE_AFTER
        or _cn_now().date().isoformat() > rec["days"][-1]
    )
    if stale:
        fresh = _fetch_throttled()
        if fresh is not None:
            rec = fresh  # else keep the stale file if we have one
    _cache = rec
    return rec["days"] if rec else None


def _parse_iso(s: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def is_trading_day(d: date) -> bool | None:
    """True/False, or None when the calendar is unavailable."""
    global _cache
    days = _days()
    if days is None:
        return None
    if d.isoformat() > days[-1]:
        # queried beyond the file's horizon — try one throttled refetch
        fresh = _fetch_throttled()
        if fresh is None or d.isoformat() > fresh["days"][-1]:
            return None
        _cache = fresh
        days = fresh["days"]
    return d.isoformat() in set(days)


def _reset() -> None:
    """Test hook: drop the in-memory cache and the fetch throttle."""
    global _cache, _last_attempt
    _cache = None
    _last_attempt = 0.0
