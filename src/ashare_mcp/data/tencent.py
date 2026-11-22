"""Tencent (qt.gtimg.cn) real-time quotes — fast multi-symbol batch source.

Wire format: GET https://qt.gtimg.cn/q=sh600519,sz000001 (gbk), records
separated by ';' as v_sh600519="f0~f1~...". ~88 fields per record.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pandas as pd
import requests

log = logging.getLogger(__name__)

_URL = "https://qt.gtimg.cn/q={symbols}"
_BATCH = 100
_WORKERS = 4
_TIMEOUT = 10

# canonical quote fields shared with akshare_data._QUOTE_COLS
QUOTE_COLS = [
    "code", "name", "price", "pct_chg", "change", "volume", "amount",
    "amplitude", "high", "low", "open", "prev_close", "volume_ratio",
    "turnover", "pe_ttm", "pb", "mkt_cap", "float_mkt_cap",
]

_F = {
    "name": 1, "code": 2, "price": 3, "prev_close": 4, "open": 5,
    "quote_time": 30, "change": 31, "pct_chg": 32, "high": 33, "low": 34,
    "volume": 36, "amount": 37, "turnover": 38, "pe_ttm": 39,
    "amplitude": 43, "float_mkt_cap": 44, "mkt_cap": 45, "pb": 46,
    "limit_up": 47, "limit_down": 48, "volume_ratio": 49,
}


def _num(v: Any, scale: float = 1.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return f * scale


def _parse_record(rec: str) -> dict[str, Any] | None:
    """Parse one v_sh600519="..." record into a canonical quote dict."""
    if "=" not in rec or "v_pv_none_match" in rec:
        return None
    left, _, right = rec.partition("=")
    prefixed = left.strip().removeprefix("v_")
    fields = right.strip().strip('"').split("~")
    if len(fields) < 50:
        return None
    f = lambda k, s=1.0: _num(fields[_F[k]], s)  # noqa: E731
    code6 = fields[_F["code"]].strip()
    if not code6:
        code6 = prefixed[-6:]
    price = f("price")
    suspended = not (price > 0)
    row = {
        "code": code6, "name": fields[_F["name"]].strip(),
        "price": float("nan") if suspended else price,
        "pct_chg": float("nan") if suspended else f("pct_chg"),
        "change": float("nan") if suspended else f("change"),
        "volume": f("volume"),                    # 手
        "amount": f("amount", 1e4),               # 万元 -> yuan
        "amplitude": f("amplitude"),
        "high": f("high"), "low": f("low"), "open": f("open"),
        "prev_close": f("prev_close"),
        "volume_ratio": f("volume_ratio"),
        "turnover": f("turnover"),
        "pe_ttm": f("pe_ttm"), "pb": f("pb"),
        "mkt_cap": f("mkt_cap", 1e8),             # 亿元 -> yuan
        "float_mkt_cap": f("float_mkt_cap", 1e8),
        "limit_up": f("limit_up"), "limit_down": f("limit_down"),
        "quote_time": _fmt_time(fields[_F["quote_time"]]),
        "_prefixed": prefixed,
    }
    return row


def _fmt_time(raw: str) -> str | None:
    """yyyymmddHHMMSS -> ISO string."""
    raw = (raw or "").strip()
    if len(raw) < 14:
        return None
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}T{raw[8:10]}:{raw[10:12]}:{raw[12:14]}"


def _fetch_batch(symbols: list[str]) -> pd.DataFrame | None:
    url = _URL.format(symbols=",".join(symbols))
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        log.warning("tencent batch failed (%d symbols): %s", len(symbols), e)
        return None
    r.encoding = "gbk"
    rows = [row for rec in r.text.split(";") if (row := _parse_record(rec.strip()))]
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetch_quotes(prefixed: list[str]) -> pd.DataFrame:
    """Fetch quotes for prefixed symbols (sh600519 / sz000001 / bj920001).

    Batches of 100, up to 4 concurrent requests. A failed batch is dropped;
    raises RuntimeError only when every batch fails.
    """
    batches = [prefixed[i:i + _BATCH] for i in range(0, len(prefixed), _BATCH)]
    frames: list[pd.DataFrame] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        for df in ex.map(_fetch_batch, batches):
            if df is None:
                failures += 1
            elif not df.empty:
                frames.append(df)
    if failures == len(batches) and not frames:
        raise RuntimeError("tencent quote fetch failed for all batches")
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    log.debug("tencent quotes: %d/%d symbols", len(out), len(prefixed))
    return out
