"""A-share industry classification: Shenwan (SW) level-1, 2021 edition.

``industry_map()`` never blocks: it returns the best available map
immediately (fresh file → stale file → bundled CSV) and, when the file is
missing or older than 7 days, kicks off ONE background thread that
refreshes ``<data_dir>/industry.json`` (throttled to one attempt per 6 h).
The in-memory cache is re-validated every 10 minutes so a long-running
server picks up weekly refreshes.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd
from urllib3.exceptions import InsecureRequestWarning

from ..config import data_dir

log = logging.getLogger(__name__)

_CN = ZoneInfo("Asia/Shanghai")
_STALE_AFTER = timedelta(days=7)
_FETCH_THROTTLE_S = 6 * 3600
_CACHE_REVALIDATE_S = 600
_PATH = "industry.json"
_BUNDLED = Path(__file__).resolve().parents[1] / "data" / "industry.csv"
_RETRIES = 3
_RETRY_SLEEP_S = 3

# SW2021 level-1 industry_code prefixes -> name
_L1 = {
    "11": "农林牧渔", "22": "基础化工", "23": "钢铁", "24": "有色金属",
    "27": "电子", "28": "汽车", "33": "家用电器", "34": "食品饮料",
    "35": "纺织服饰", "36": "轻工制造", "37": "医药生物", "41": "公用事业",
    "42": "交通运输", "43": "房地产", "45": "商贸零售", "46": "社会服务",
    "48": "银行", "49": "非银金融", "51": "综合", "61": "建筑材料",
    "62": "建筑装饰", "63": "电力设备", "64": "机械设备", "65": "国防军工",
    "71": "计算机", "72": "传媒", "73": "通信", "74": "煤炭",
    "75": "石油石化", "76": "环保", "77": "美容护理",
}
_LEGACY = {"21", "25", "26", "31", "32", "44", "47"}  # SW2014 leftovers

_cache: dict[str, str] | None = None
_cache_ts: float = 0.0
_last_attempt: float = 0.0
_refresh_lock = threading.Lock()
_refreshing = False


def _cn_now() -> datetime:
    return datetime.now(_CN).replace(tzinfo=None)


def _transform(df: pd.DataFrame) -> dict[str, str]:
    """code6 -> SW L1 name; latest start_date wins; unmapped prefixes dropped."""
    df = df.sort_values("start_date").drop_duplicates("symbol", keep="last")
    out = {}
    for row in df.itertuples():
        code6 = str(row.symbol).strip()[-6:]
        name = _L1.get(str(row.industry_code).strip()[:2])
        if code6 and name:
            out[code6] = name
    return out


def _raw_frame() -> pd.DataFrame:
    """ak.stock_industry_clf_hist_sw() with retries; akshare's own
    InsecureRequestWarning is suppressed locally around the call."""
    last = None
    for i in range(_RETRIES):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                return ak.stock_industry_clf_hist_sw()
        except Exception as e:
            last = e
            log.warning("sw industry fetch attempt %d failed: %s", i + 1, e)
            time.sleep(_RETRY_SLEEP_S)
    raise last  # type: ignore[misc]


def _fetch_and_persist() -> dict[str, str]:
    m = _transform(_raw_frame())
    if not m:
        raise RuntimeError("sw industry fetch produced no rows")
    rec = {"fetched_at": _cn_now().isoformat(timespec="seconds"), "map": m}
    try:
        (data_dir() / _PATH).write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        log.warning("cannot persist industry map: %s", e)
    return m


def _load_file() -> dict | None:
    try:
        d = json.loads((data_dir() / _PATH).read_text(encoding="utf-8"))
        if isinstance(d.get("map"), dict):
            return d
    except Exception:
        pass
    return None


def _parse_iso(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def _fresh(rec: dict | None) -> bool:
    ts = _parse_iso((rec or {}).get("fetched_at"))
    return bool(ts and rec.get("map") and _cn_now() - ts <= _STALE_AFTER)


def _bundled() -> dict[str, str]:
    if not _BUNDLED.exists():
        return {}
    df = pd.read_csv(_BUNDLED, dtype=str)
    return {str(r.code6)[-6:]: str(r.industry)
            for r in df.itertuples() if pd.notna(r.code6)}


def _refresh_worker() -> None:
    global _cache, _cache_ts, _refreshing
    try:
        m = _fetch_and_persist()
        _cache, _cache_ts = m, time.time()
        log.info("industry map refreshed: %d codes", len(m))
    except Exception as e:
        log.warning("industry refresh failed: %s", e)
    finally:
        with _refresh_lock:
            _refreshing = False


def _maybe_refresh() -> None:
    """Start the single background refresh when due (6 h throttle)."""
    global _refreshing, _last_attempt
    if time.time() - _last_attempt < _FETCH_THROTTLE_S:
        return
    with _refresh_lock:
        if _refreshing or time.time() - _last_attempt < _FETCH_THROTTLE_S:
            return
        _refreshing = True
        _last_attempt = time.time()
    threading.Thread(target=_refresh_worker, daemon=True).start()


def industry_map() -> dict[str, str]:
    """code6 -> SW L1 name. Non-blocking; best available map immediately."""
    global _cache, _cache_ts
    now = time.time()
    if _cache is not None and now - _cache_ts < _CACHE_REVALIDATE_S:
        return _cache
    rec = _load_file()
    m = (rec or {}).get("map") or _bundled()
    # cache first so the background refresh's swap always wins the race
    _cache, _cache_ts = m, now
    if not _fresh(rec):
        _maybe_refresh()
    return m


def list_industries() -> list[dict]:
    """[{name, count}] sorted by member count, descending."""
    from collections import Counter
    counts = Counter(industry_map().values())
    return [{"name": n, "count": c} for n, c in counts.most_common()]


def _reset() -> None:
    """Test hook: drop the cache, throttle and refresh flag."""
    global _cache, _cache_ts, _last_attempt, _refreshing
    _cache = None
    _cache_ts = 0.0
    _last_attempt = 0.0
    _refreshing = False
