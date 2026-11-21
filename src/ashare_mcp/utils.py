"""Shared helpers: symbol normalization, dates, DataFrame -> JSON records."""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd


def normalize_symbol(symbol: str) -> tuple[str, str]:
    """Normalize an A-share symbol to ``(code6, market)``.

    Accepts ``"000001"``, ``"sz000001"``, ``"SZ000001"``, ``"000001.SZ"``,
    ``"sh600000"``. ``market`` is one of ``"sh"``, ``"sz"``, ``"bj"``.
    """
    s = symbol.strip().lower()
    if not s:
        raise ValueError("empty symbol")

    if "." in s:
        code, mkt = s.split(".", 1)
        code6 = _digits(code)
        mkt = mkt.strip()
        if mkt in ("sh", "sz", "bj"):
            return code6, mkt
        return code6, _market_of(code6)

    for prefix in ("sh", "sz", "bj"):
        if s.startswith(prefix) and len(s) > 6:
            return _digits(s[len(prefix):]), prefix

    code6 = _digits(s)
    return code6, _market_of(code6)


def _digits(code: str) -> str:
    digits = re.sub(r"\D", "", code)
    if len(digits) < 6:
        raise ValueError(f"invalid stock symbol: {code!r}")
    return digits[-6:]


def _market_of(code6: str) -> str:
    # Beijing SE codes: 43/83/87/88/92 prefixes
    if code6.startswith("92") or code6[0] in "48":
        return "bj"
    if code6[0] == "6":
        return "sh"  # 60/68 A-shares
    if code6[0] == "9":
        return "sh"  # 90 Shanghai B-shares
    if code6[0] in "03":
        return "sz"  # 00/30 A-shares
    if code6[0] == "2":
        return "sz"  # 20 Shenzhen B-shares
    if code6.startswith("12"):
        return "sh"  # SH bonds
    if code6[0] == "1":
        return "sz"  # SZ funds/bonds
    if code6[0] == "5":
        return "sh"  # SH funds (51x/56x/58x)
    return "sh"


def ts_code(code6: str, market: str) -> str:
    """tushare-style code, e.g. ``000001.SZ``."""
    return f"{code6}.{market.upper()}"


def sina_symbol(code6: str, market: str) -> str:
    """Sina-style code, e.g. ``sz000001``."""
    return f"{market}{code6}"


def normalize_date(d: str | None, default: str | None = None) -> str:
    """Normalize ``2024-01-01`` / ``20240101`` to ``YYYYMMDD``.

    ``None``/empty returns ``default`` (which may itself be ``None``).
    """
    if d is None or not str(d).strip():
        if default is None:
            return ""
        d = default
    digits = re.sub(r"\D", "", str(d))
    if len(digits) == 8:
        return digits
    if len(digits) == 6:
        return digits + "01"
    raise ValueError(f"invalid date: {d!r} (expected YYYYMMDD or YYYY-MM-DD)")


def limit_pct_for(code6: str, name: str = "") -> float:
    """Daily price-limit ratio for an A-share."""
    if "ST" in name.upper() or "退" in name:
        return 0.05
    if code6.startswith(("30", "68")):
        return 0.20  # ChiNext / STAR
    if code6.startswith(("8", "4", "92")):
        return 0.30  # Beijing SE
    return 0.10


def is_index_symbol(symbol: str) -> bool:
    """Heuristic: explicit index-style symbols like sh000001 / sz399001."""
    s = symbol.strip().lower()
    if s.startswith(("sh000", "sz399")):
        return True
    return False


def resample_ohlcv(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Resample daily OHLCV bars to weekly/monthly.

    Expects columns ``date`` (YYYY-MM-DD), ``open``, ``high``, ``low``,
    ``close``, ``volume``, ``amount``.
    """
    rule = {"weekly": "W-FRI", "monthly": "ME"}.get(period)
    if rule is None:
        return df
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date").sort_index()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last",
           "volume": "sum", "amount": "sum"}
    agg = {k: v for k, v in agg.items() if k in d.columns}
    out = d.resample(rule).agg(agg).dropna(subset=["close"])
    out = out.reset_index()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    if "pct_chg" in df.columns or "close" in out.columns:
        out["pct_chg"] = out["close"].pct_change() * 100
    return out


def df_records(df: pd.DataFrame | None, limit: int | None = None,
               orient: str = "records") -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON-safe records, rounding floats."""
    if df is None or df.empty:
        return []
    if limit is not None and len(df) > limit:
        df = df.tail(limit)
    df = df.astype(object).where(pd.notna(df), None)
    records = df.to_dict(orient=orient)
    for row in records:
        for k, v in row.items():
            if isinstance(v, float):
                row[k] = round(v, 6) if math.isfinite(v) else None
            elif isinstance(v, pd.Timestamp):
                row[k] = v.strftime("%Y-%m-%d")
    return records
