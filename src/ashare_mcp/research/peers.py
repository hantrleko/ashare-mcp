"""Industry peers comparison and valuation percentiles (SW L1)."""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from ..data import akshare_data as ad
from .industry import industry_map
from .screener import _clean

FIELDS = ["price", "pct_chg", "pe_ttm", "pb", "roe_est",
          "mkt_cap", "turnover"]
PCT_FIELDS = ["pe_ttm", "pb", "roe_est", "mkt_cap"]


def _pctile(values: list[float], x: float | None) -> float | None:
    """Mid-rank percentile of x in values (0-100): (below + ties/2) / n.
    Lower value -> lower percentile; None when x invalid."""
    vals = [v for v in values if v is not None
            and math.isfinite(v) and v > 0]
    if x is None or not math.isfinite(x) or x <= 0 or not vals:
        return None
    below = sum(1 for v in vals if v < x)
    ties = sum(1 for v in vals if v == x)
    return round(100 * (below + 0.5 * ties) / len(vals), 1)


def industry_peers(symbol: str, limit: int = 30) -> dict[str, Any]:
    code6 = re.sub(r"\D", "", str(symbol))[-6:]
    limit = max(1, min(int(limit), 500))
    spot = ad._spot_df().copy()
    imap = industry_map()
    spot["code6"] = spot["code6"].astype(str).str[-6:]
    spot["industry"] = spot["code6"].map(
        lambda c: imap.get(c, "未分类"))
    pe = pd.to_numeric(spot["pe_ttm"], errors="coerce")
    pb = pd.to_numeric(spot["pb"], errors="coerce")
    spot["roe_est"] = (pb / pe * 100).where((pb > 0) & (pe > 0))
    for f in FIELDS:
        spot[f] = pd.to_numeric(spot[f], errors="coerce")

    me = spot[spot["code6"] == code6]
    if me.empty:
        raise ValueError(f"unknown symbol in spot snapshot: {code6}")
    ind = str(me.iloc[0]["industry"])
    pool = spot[spot["industry"] == ind].copy()
    pool = pool.sort_values("mkt_cap", ascending=False,
                            na_position="last")
    count = len(pool)
    top = pool.head(limit)

    vals = {f: [v for v in pool[f]
                if v is not None and math.isfinite(v) and v > 0]
            for f in PCT_FIELDS}
    medians = {f: (_clean(float(pd.Series(vals[f]).median()))
                   if vals[f] else None) for f in PCT_FIELDS}

    def _row(r) -> dict[str, Any]:
        d = {"code": str(r["code6"]), "name": str(r["name"]),
             "is_me": bool(r["code6"] == code6)}
        for f in FIELDS:
            v = r[f]
            d[f] = _clean(None if v is None or not math.isfinite(v)
                          else float(v))
        return d

    peers = [_row(r) for r in top.to_dict("records")]
    stock = _row(me.iloc[0])
    stock["industry"] = ind
    stock["percentiles"] = {
        f: _pctile(vals[f], me.iloc[0][f]) for f in PCT_FIELDS}
    return {"industry": ind, "count": count, "stock": stock,
            "peers": peers, "medians": medians}
