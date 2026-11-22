"""Stock screener over the full-market quote snapshot."""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pandas as pd

from ..data import akshare_data as ad
from ..data.facade import market_data
from .industry import industry_map

RANGE_FIELDS = {
    "price", "pct_chg", "turnover", "pe_ttm", "pb", "roe_est",
    "mkt_cap", "float_mkt_cap", "amount", "volume_ratio", "amplitude",
}
MOM_FIELDS = {"mom_20": 20, "mom_60": 60}
BOARDS = {"main", "chinext", "star", "bse"}
SORT_FIELDS = RANGE_FIELDS | set(MOM_FIELDS) | {"code", "name", "industry"}
_MOM_LIMIT = 200
_MOM_WORKERS = 4

NOTES = ["roe_est = PB/PE（估算，非财报ROE）", "行业：申万一级（2021版）"]


def _board_of(code6: str) -> str:
    if code6.startswith("30"):
        return "chinext"
    if code6.startswith("68"):
        return "star"
    if code6.startswith(("4", "8", "92")):
        return "bse"
    return "main"


def _active(rng) -> bool:
    """A [min, max] pair is active when at least one bound is a number."""
    try:
        return any(v is not None and not pd.isna(v) for v in rng[:2])
    except (TypeError, IndexError):
        return False


def _mom(code6: str, n: int) -> float:
    """% change of close over the last n daily qfq bars; NaN on failure."""
    try:
        bars, _ = market_data.call(
            "get_kline", code6, period="daily", adjust="qfq")
        closes = [b["close"] for b in bars
                  if b.get("close") is not None]
        if len(closes) < n + 1 or not closes[-n - 1]:
            return float("nan")
        return (closes[-1] / closes[-n - 1] - 1) * 100
    except Exception:
        return float("nan")


def _clean(v: Any) -> Any:
    """JSON-safe scalar: NaN/inf -> None."""
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and not math.isfinite(v)) else v
    return v


def screen(ranges: dict[str, list] | None = None,
           industries: list[str] | None = None,
           boards: list[str] | None = None,
           exclude_st: bool = True,
           exclude_suspended: bool = True,
           momentum: dict[str, list] | None = None,
           sort_by: str = "mkt_cap", desc: bool = True,
           limit: int = 100) -> dict[str, Any]:
    ranges = dict(ranges or {})
    momentum = dict(momentum or {})
    industries = list(industries or [])
    boards = list(boards or [])

    for f in ranges:
        if f not in RANGE_FIELDS:
            raise ValueError(f"unknown range field: {f}")
    for f in momentum:
        if f not in MOM_FIELDS:
            raise ValueError(f"unknown momentum field: {f}")
    for b in boards:
        if b not in BOARDS:
            raise ValueError(f"unknown board: {b}")
    if sort_by not in SORT_FIELDS:
        raise ValueError(f"unknown sort field: {sort_by}")
    limit = max(1, min(int(limit), 500))

    spot = ad._spot_df().copy()
    total = len(spot)
    imap = industry_map()
    spot["industry"] = spot["code6"].map(
        lambda c: imap.get(str(c)[-6:], "未分类"))
    spot["board"] = spot["code6"].astype(str).str[-6:].map(_board_of)
    spot["is_st"] = spot["name"].astype(str).str.upper().str.contains("ST")
    pe = pd.to_numeric(spot["pe_ttm"], errors="coerce")
    pb = pd.to_numeric(spot["pb"], errors="coerce")
    spot["roe_est"] = (pb / pe * 100).where((pb > 0) & (pe > 0))

    df = spot
    if exclude_st:
        df = df[~df["is_st"]]
    if exclude_suspended:
        df = df[pd.to_numeric(df["price"], errors="coerce").notna()
                & (pd.to_numeric(df["price"], errors="coerce") > 0)]
    if industries:
        df = df[df["industry"].isin(industries)]
    if boards:
        df = df[df["board"].isin(boards)]
    for f, rng in ranges.items():
        if not _active(rng):
            continue
        col = pd.to_numeric(df[f], errors="coerce")
        lo, hi = rng[0], rng[1] if len(rng) > 1 else None
        m = col.notna()
        if lo is not None:
            m &= col >= lo
        if hi is not None:
            m &= col <= hi
        df = df[m]

    need_mom = sort_by in MOM_FIELDS or any(
        _active(rng) for rng in momentum.values())
    if need_mom:
        n = len(df)
        if n > _MOM_LIMIT:
            raise ValueError(
                f"候选 {n} 只，动量筛选上限 200，请先收紧其他条件")
        want = {f: MOM_FIELDS[f] for f in MOM_FIELDS
                if f in momentum or f == sort_by}
        codes = df["code6"].astype(str).tolist()
        with ThreadPoolExecutor(max_workers=_MOM_WORKERS) as ex:
            for f, bars in want.items():
                df[f] = list(ex.map(lambda c, b=bars: _mom(c, b), codes))
        for f, rng in momentum.items():
            if not _active(rng):
                continue
            col = pd.to_numeric(df[f], errors="coerce")
            lo, hi = rng[0], rng[1] if len(rng) > 1 else None
            m = col.notna()
            if lo is not None:
                m &= col >= lo
            if hi is not None:
                m &= col <= hi
            df = df[m]
    else:
        want = {}

    asc = not desc
    df = df.sort_values(sort_by, ascending=asc, na_position="last")
    matched = len(df)

    cols = ["code6", "name", "industry", "board", "price", "pct_chg",
            "turnover", "pe_ttm", "pb", "roe_est", "mkt_cap",
            "float_mkt_cap", "amount", "volume_ratio", *want]
    rows = []
    for rec in df.head(limit)[cols].to_dict("records"):
        rec["code"] = rec.pop("code6")
        rows.append({k: _clean(v) for k, v in rec.items()})
    as_of = ""
    if "quote_time" in df.columns:
        qt = df["quote_time"].dropna()
        if len(qt):
            as_of = str(qt.max())
    return {"total_universe": total, "matched": matched, "rows": rows,
            "as_of": as_of, "notes": NOTES}
