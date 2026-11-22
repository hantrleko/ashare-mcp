"""akshare data source — primary provider (free, no token required).

Source strategy: prefer Sina/Tencent endpoints for quotes and klines to
avoid East Money push2 rate limits; EM endpoints are kept as fallback with
a cooldown once a Push2RateLimitError is seen.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import threading
from typing import Any

import akshare as ak
import numpy as np
import pandas as pd


def _patch_mini_racer() -> None:
    """Serialize py_mini_racer entry points.

    akshare uses MiniRacer (V8 via a native dll) for JS-encoded sina
    responses; concurrent use segfaults the whole process.  Patching the
    class methods with one RLock covers every import style akshare uses,
    while leaving other providers (e.g. Tencent/EM) fully concurrent.
    Idempotent: skips classes already patched.
    """
    try:
        from py_mini_racer import MiniRacer
    except Exception:
        return
    if getattr(MiniRacer, "_ashare_lock_patched", False):
        return
    lock = threading.RLock()

    def wrap(name: str) -> None:
        fn = getattr(MiniRacer, name, None)
        if fn is None or getattr(fn, "_ashare_wrapped", False):
            return

        def locked(self: Any, *a: Any, _fn: Any = fn, **k: Any) -> Any:
            with lock:
                return _fn(self, *a, **k)

        locked._ashare_wrapped = True  # type: ignore[attr-defined]
        setattr(MiniRacer, name, locked)

    for name in ("__init__", "eval", "execute", "call"):
        wrap(name)
    MiniRacer._ashare_lock_patched = True  # type: ignore[attr-defined]


_patch_mini_racer()

from ..utils import (
    _market_of,
    df_records,
    normalize_date,
    normalize_symbol,
    resample_ohlcv,
    sina_symbol,
    ts_code,
)
from . import store, tencent

log = logging.getLogger(__name__)

_SPOT_TTL = 60.0
_INDEX_TTL = 60.0
_LIST_TTL = 3600.0
_EM_BAN_SECONDS = 600.0

_caches: dict[str, Any] = {}
_em_banned_until = 0.0

_KLINE_RENAME = {
    "日期": "date", "股票代码": "code", "开盘": "open", "收盘": "close",
    "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
    "振幅": "amplitude", "涨跌幅": "pct_chg", "涨跌额": "change",
    "换手率": "turnover",
}
_KLINE_COLS = ["date", "code", "open", "high", "low", "close", "volume",
               "amount", "amplitude", "pct_chg", "change", "turnover"]

# canonical quote columns produced by _norm_spot
_QUOTE_COLS = ["code6", "name", "price", "pct_chg", "change", "volume",
               "amount", "amplitude", "high", "low", "open", "prev_close",
               "volume_ratio", "turnover", "pe_ttm", "pb", "mkt_cap",
               "float_mkt_cap"]

_LIMIT_POOL_FUNCS = {
    "zt": "stock_zt_pool_em",              # 涨停股池 (最近约30个交易日)
    "dt": "stock_zt_pool_dtgc_em",        # 跌停股池
    "prev": "stock_zt_pool_previous_em",  # 昨日涨停
    "strong": "stock_zt_pool_strong_em",  # 强势股池
    "zb": "stock_zt_pool_zbgc_em",        # 炸板股池
    "new": "stock_zt_pool_sub_new_em",    # 次新股池
}

_MONEY_FLOW_COLS = [
    "日期", "收盘价", "涨跌幅",
    "主力净流入-净额", "主力净流入-净占比",
    "超大单净流入-净额", "超大单净流入-净占比",
    "大单净流入-净额", "大单净流入-净占比",
    "中单净流入-净额", "小单净流入-净额",
]

_STATEMENT_MAP = {
    "income": "利润表",
    "balance": "资产负债表",
    "cashflow": "现金流量表",
}


def _em_available() -> bool:
    return time.time() >= _em_banned_until


def _note_em_result(exc: Exception) -> None:
    global _em_banned_until
    name = type(exc).__name__
    msg = str(exc)
    if "Push2" in name or "限流" in msg or "push2" in msg:
        _em_banned_until = time.time() + _EM_BAN_SECONDS


# ---------------- caches ----------------

def _cached(key: str, ttl: float, loader) -> Any:
    hit = _caches.get(key)
    if hit and time.time() - hit["ts"] < ttl:
        return hit["df"]
    df = loader()
    _caches[key] = {"ts": time.time(), "df": df}
    return df


# ---------------- normalization ----------------

def _norm_kline(df: pd.DataFrame, period: str) -> pd.DataFrame:
    df = df.rename(columns={k: v for k, v in _KLINE_RENAME.items() if k in df.columns})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    if "pct_chg" not in df.columns and "close" in df.columns:
        df["pct_chg"] = df["close"].pct_change() * 100
    if period != "daily":
        df = resample_ohlcv(df, period)
    keep = [c for c in _KLINE_COLS if c in df.columns]
    return df[keep].sort_values("date").reset_index(drop=True)


def _norm_spot_em(df: pd.DataFrame) -> pd.DataFrame:
    """East Money spot snapshot -> canonical columns."""
    out = pd.DataFrame()
    out["name"] = df.get("名称")
    code_col = df.get("代码")
    out["code6"] = (code_col.astype(str).str.replace(r"\D", "", regex=True)
                    .str[-6:])
    m = {
        "最新价": "price", "涨跌幅": "pct_chg", "涨跌额": "change",
        "成交量": "volume", "成交额": "amount", "振幅": "amplitude",
        "最高": "high", "最低": "low", "今开": "open", "昨收": "prev_close",
        "量比": "volume_ratio", "换手率": "turnover",
        "市盈率-动态": "pe_ttm", "市净率": "pb", "总市值": "mkt_cap",
        "流通市值": "float_mkt_cap",
    }
    for src, dst in m.items():
        if src in df.columns:
            out[dst] = pd.to_numeric(df[src], errors="coerce")
    return out[_QUOTE_COLS]


def _norm_spot_sina(df: pd.DataFrame) -> pd.DataFrame:
    """Sina spot snapshot -> canonical columns. 代码 like 'sh600519'."""
    out = pd.DataFrame()
    code_col = df.get("代码", pd.Series(dtype=str)).astype(str)
    out["code6"] = code_col.str.replace(r"[^0-9]", "", regex=True).str[-6:]
    out["name"] = df.get("名称")
    m = {
        "最新价": "price", "涨跌幅": "pct_chg", "涨跌额": "change",
        "成交量": "volume", "成交额": "amount",
        "最高": "high", "最低": "low", "今开": "open", "昨收": "prev_close",
    }
    for src, dst in m.items():
        if src in df.columns:
            out[dst] = pd.to_numeric(df[src], errors="coerce")
    for c in _QUOTE_COLS:
        if c not in out.columns:
            out[c] = pd.NA
    return out[_QUOTE_COLS]


def _load_em_spot() -> pd.DataFrame:
    return _norm_spot_em(ak.stock_zh_a_spot_em())


def _load_sina_spot() -> pd.DataFrame:
    return _norm_spot_sina(ak.stock_zh_a_spot_sina())


def _em_spot_df() -> pd.DataFrame:
    return _cached("spot_em", _SPOT_TTL, _load_em_spot)


def _sina_spot_df() -> pd.DataFrame:
    return _cached("spot_sina", _SPOT_TTL, _load_sina_spot)


def _load_tencent_spot() -> pd.DataFrame:
    """Full-market spot via Tencent (fast batch endpoint)."""
    # universe: reuse a fresh cached live list, else the bundled snapshot —
    # never block the spot path on the slow live list fetch
    hit = _caches.get("stock_list")
    if hit and time.time() - hit["ts"] < _LIST_TTL:
        lst = hit["df"]
    else:
        lst = _bundled_stock_list()
        if not len(lst):
            lst = _stock_list_df()
    syms = [sina_symbol(c, m) for c, m in zip(lst["code6"], lst["market"])]
    df = tencent.fetch_quotes(syms)
    if df.empty:
        raise RuntimeError("tencent spot snapshot empty")
    return df.rename(columns={"code": "code6"})


def _load_spot() -> pd.DataFrame:
    try:
        return _load_tencent_spot()
    except Exception as e:
        log.warning("tencent spot failed, falling back: %s", e)
    if _em_available():
        try:
            return _em_spot_df()
        except Exception as e:
            _note_em_result(e)
    return _sina_spot_df()


def _spot_df() -> pd.DataFrame:
    return _cached("spot", _SPOT_TTL, _load_spot)


def _load_index_spot() -> pd.DataFrame:
    df = ak.index_zh_spot_sina()
    code_col = df.get("代码", pd.Series(dtype=str)).astype(str)
    out = pd.DataFrame()
    out["code"] = code_col  # 'sh000001' style
    out["code6"] = code_col.str.replace(r"[^0-9]", "", regex=True).str[-6:]
    out["name"] = df.get("名称")
    m = {
        "最新价": "price", "涨跌幅": "pct_chg", "涨跌额": "change",
        "成交量": "volume", "成交额": "amount",
        "最高": "high", "最低": "low", "今开": "open", "昨收": "prev_close",
    }
    for src, dst in m.items():
        if src in df.columns:
            out[dst] = pd.to_numeric(df[src], errors="coerce")
    return out


def _index_spot_df() -> pd.DataFrame:
    return _cached("index_spot", _INDEX_TTL, _load_index_spot)


def _bundled_stock_list() -> pd.DataFrame:
    """Snapshot shipped inside the package (built by scripts/build_stock_list.py)."""
    path = Path(__file__).resolve().parent / "stock_list.csv"
    if not path.exists():
        return pd.DataFrame(columns=["code6", "name", "market"])
    df = pd.read_csv(path, dtype=str)
    df = df.dropna(subset=["code6"])
    df["code6"] = df["code6"].str[-6:]
    df["market"] = df["code6"].map(_market_of)
    return df[["code6", "name", "market"]]


def _load_stock_list() -> pd.DataFrame:
    """All A-shares -> columns code6/name/market.

    Union of whatever live sources succeed and the bundled snapshot:
    live rows win on name, the snapshot fills in codes the live sources
    missed (e.g. when the SSE endpoint is unreachable).
    """
    live: list[pd.DataFrame] = []
    try:
        df = ak.stock_info_a_code_name()
        code_col = next((c for c in ("A股代码", "证券代码", "代码") if c in df.columns), None)
        name_col = next((c for c in ("A股简称", "证券简称", "名称") if c in df.columns), None)
        if code_col and name_col:
            if "A股代码" in df.columns:
                df = df[df["A股代码"].notna()]
                code_col, name_col = "A股代码", "A股简称"
            out = pd.DataFrame({
                "code6": df[code_col].astype(str).str.replace(r"\D", "", regex=True).str[-6:],
                "name": df[name_col].astype(str),
                "market": "",
            })
            live.append(out)
    except Exception:
        pass
    # per-exchange lists fill any market the combined list missed
    have = set()
    if live:
        have = set(live[0]["code6"].map(_market_of).unique())
    for fn, c_col, n_col, mkt in (
        ("stock_info_sh_name_code", "证券代码", "证券简称", "sh"),
        ("stock_info_sz_name_code", "A股代码", "A股简称", "sz"),
        ("stock_info_bj_name_code", "证券代码", "证券简称", "bj"),
    ):
        if mkt in have:
            continue
        try:
            d = getattr(ak, fn)()
            if c_col in d.columns and n_col in d.columns:
                live.append(pd.DataFrame({
                    "code6": d[c_col].astype(str).str.replace(r"\D", "", regex=True).str[-6:],
                    "name": d[n_col].astype(str),
                    "market": mkt,
                }))
        except Exception:
            continue

    snap = _bundled_stock_list()
    frames = live + ([snap] if len(snap) else [])
    if not frames:
        raise RuntimeError("stock list unavailable")
    out = pd.concat(frames, ignore_index=True).dropna(subset=["code6", "name"])
    # live rows first -> keep="first" gives live precedence on dedupe
    out = out.drop_duplicates("code6", keep="first")
    out["market"] = out["code6"].map(_market_of)
    return out.reset_index(drop=True)


def _stock_list_df() -> pd.DataFrame:
    return _cached("stock_list", _LIST_TTL, _load_stock_list)


# ---------------- public functions ----------------

def search_stock(query: str, limit: int = 10) -> list[dict[str, Any]]:
    df = _stock_list_df()
    q = str(query).strip()
    q_digits = "".join(ch for ch in q if ch.isdigit())
    mask = df["name"].str.contains(q, na=False)
    if q_digits:
        mask |= df["code6"].str.contains(q_digits, na=False)
    hits = df[mask].copy()

    def sort_key(r):
        exact = 0 if q_digits and r["code6"] == q_digits else 1
        prefix = 0 if str(r["name"]).startswith(q) else 1
        return (exact, prefix, r["code6"])

    hits["_k"] = hits.apply(sort_key, axis=1)
    hits = hits.sort_values("_k").head(limit)
    return hits[["code6", "name", "market"]].rename(
        columns={"code6": "code"}).to_dict("records")


def _quote_from_spot(df: pd.DataFrame, code6: str,
                     prefixed: str | None = None) -> dict[str, Any]:
    if prefixed is not None and "code" in df.columns:
        mask = df["code"] == prefixed
    else:
        mask = df["code6"] == code6
    hits = df[mask]
    if hits.empty:
        raise KeyError(f"symbol {code6} not found in quote snapshot")
    row = hits.iloc[0]
    out = {}
    for k, v in row.items():
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            continue
        if isinstance(v, (int, float, np.integer, np.floating)):
            fv = float(v)
            out[k] = int(fv) if fv.is_integer() and abs(fv) < 1e15 else round(fv, 6)
        else:
            out[k] = v
    out["code"] = code6
    return out


def _name_of(code6: str) -> str:
    try:
        df = _stock_list_df()
        hits = df[df["code6"] == code6]
        return str(hits.iloc[0]["name"]) if len(hits) else ""
    except Exception:
        return ""


def _minute_quote(code6: str, mkt: str) -> dict[str, Any]:
    """Near-realtime quote from the latest 1-minute Sina bar."""
    sina_sym = sina_symbol(code6, mkt)
    bars = ak.stock_zh_a_hist_min_sina(symbol=sina_sym, period="1")
    if bars is None or bars.empty:
        raise KeyError(f"no minute data for {code6}")
    last = bars.iloc[-1]
    today = date.today()
    sd = (today - pd.Timedelta(days=120)).strftime("%Y%m%d")
    daily = ak.stock_zh_a_hist_sina(
        symbol=sina_sym, period="daily", start_date=sd,
        end_date=today.strftime("%Y%m%d"), adjust="")
    if daily is None or daily.empty:
        raise KeyError(f"no daily data for {code6}")
    prev = float(daily.iloc[-2]["close"]) if len(daily) > 1 else float(daily.iloc[-1]["close"])
    price = float(last["close"])
    return {
        "code": code6, "name": _name_of(code6), "price": price,
        "prev_close": prev,
        "pct_chg": round((price / prev - 1) * 100, 3) if prev else None,
        "date": str(last.get("day", "")),
        "volume": float(last.get("volume") or 0),
        "amount": float(last.get("amount") or 0),
        "note": "latest 1-min bar (spot snapshot unavailable)",
    }


def _last_close_quote(code6: str, mkt: str) -> dict[str, Any]:
    """Last-resort quote from the latest daily bar (not realtime)."""
    today = date.today()
    sd = (today - pd.Timedelta(days=10)).strftime("%Y%m%d")
    bars = ak.stock_zh_a_hist_sina(
        symbol=sina_symbol(code6, mkt), period="daily",
        start_date=sd, end_date=today.strftime("%Y%m%d"), adjust="")
    if bars is None or bars.empty:
        raise KeyError(f"no data for {code6}")
    last, prev = bars.iloc[-1], (bars.iloc[-2] if len(bars) > 1 else bars.iloc[-1])
    return {
        "code": code6, "name": _name_of(code6), "price": float(last["close"]),
        "prev_close": float(prev["close"]),
        "pct_chg": round((float(last["close"]) / float(prev["close"]) - 1) * 100, 3)
        if float(prev["close"]) else None,
        "date": str(last["date"]),
        "note": "latest daily close (spot unavailable)",
    }


def get_quote(symbol: str) -> dict[str, Any]:
    """Single-symbol quote: Tencent -> EM spot -> 1-min bar -> Sina spot -> daily close."""
    code6, mkt = normalize_symbol(symbol)
    try:
        df = tencent.fetch_quotes([sina_symbol(code6, mkt)])
        if not df.empty:
            return _quote_from_spot(df.rename(columns={"code": "code6"}), code6)
    except Exception:
        pass
    if _em_available():
        try:
            return _quote_from_spot(_em_spot_df(), code6)
        except Exception as e:
            _note_em_result(e)
    for fallback in (_minute_quote, _last_close_quote):
        try:
            return fallback(code6, mkt)
        except Exception:
            continue
    try:
        return _quote_from_spot(_sina_spot_df(), code6)
    except Exception as e:
        raise RuntimeError(f"no quote data for {symbol}: {e}")


def get_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    """Batch quotes: one Tencent multi-symbol fetch, per-symbol fallback
    (_minute_quote / _last_close_quote) for whatever it misses."""
    norm = [normalize_symbol(s) for s in symbols]
    tmap: dict[str, dict[str, Any]] = {}
    try:
        df = tencent.fetch_quotes(
            [sina_symbol(c, m) for c, m in norm]).rename(columns={"code": "code6"})
        for code6 in df["code6"]:
            try:
                tmap[code6] = _quote_from_spot(df, code6)
            except Exception:
                continue
    except Exception as e:
        log.warning("tencent quotes failed, per-symbol fallback: %s", e)
    out = []
    for s, (code6, mkt) in zip(symbols, norm):
        row = tmap.get(code6)
        if row is None:
            for fallback in (_minute_quote, _last_close_quote):
                try:
                    row = fallback(code6, mkt)
                    break
                except Exception:
                    continue
        out.append(row if row is not None else {"code": code6, "error": "no quote data"})
    return out


def _norm_index_symbol(symbol: str) -> str:
    s = symbol.strip().lower()
    if s.startswith(("sh", "sz", "bj")) and len(s) >= 8:
        return s[:8]
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        raise ValueError(f"invalid index symbol: {symbol!r}")
    code6 = digits[-6:]
    if code6.startswith("399"):
        return "sz" + code6
    if code6.startswith("89"):
        return "bj" + code6
    return "sh" + code6


def get_index_quote(symbol: str = "sh000001") -> dict[str, Any]:
    idx = _norm_index_symbol(symbol)
    return _quote_from_spot(_index_spot_df(), idx[2:], prefixed=idx)


_INDEX_BOARD = [
    ("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指"),
    ("sh000688", "科创50"), ("sh000300", "沪深300"), ("sh000905", "中证500"),
    ("sh000852", "中证1000"), ("sh000016", "上证50"), ("sz399107", "深证A指"),
    ("bj899050", "北证50"),
]


_DIST_BINS = [-9, -7, -5, -3, -1, 0, 1, 3, 5, 7, 9]
_DIST_LABELS = ["≤-9", "-9~-7", "-7~-5", "-5~-3", "-3~-1", "-1~0", "0",
                "0~1", "1~3", "3~5", "5~7", "7~9", "≥9"]


def _pct_distribution(pct: pd.Series) -> list[dict[str, Any]]:
    """Counts per pct_chg bucket; exact-0 is its own bucket."""
    pct = pct.dropna()
    counts = []
    for i, label in enumerate(_DIST_LABELS):
        if label == "0":
            n = int((pct == 0).sum())
        elif i == 0:
            n = int((pct <= _DIST_BINS[0]).sum())
        elif i == len(_DIST_LABELS) - 1:
            n = int((pct >= _DIST_BINS[-1]).sum())
        else:
            j = i - 1 if i <= 5 else i - 2
            lo, hi = _DIST_BINS[j], _DIST_BINS[j + 1]
            if hi == 0:
                n = int(((pct > lo) & (pct < 0)).sum())
            else:
                n = int(((pct > lo) & (pct <= hi)).sum())
        counts.append({"range": label, "count": n})
    return counts


def get_market_overview() -> dict[str, Any]:
    idx_df = _index_spot_df()
    indices = []
    for sym, name in _INDEX_BOARD:
        try:
            q = _quote_from_spot(idx_df, sym[2:], prefixed=sym)
            q["name"] = name
            indices.append(q)
        except Exception:
            continue

    spot = _spot_df()
    breadth: dict[str, Any] = {}
    if "pct_chg" in spot.columns:
        pct = pd.to_numeric(spot["pct_chg"], errors="coerce")
        breadth = {
            "advance": int((pct > 0).sum()),
            "decline": int((pct < 0).sum()),
            "flat": int((pct == 0).sum()),
            "avg_pct_chg": round(float(pct.mean()), 3),
            "distribution": _pct_distribution(pct),
            "limit_up": int((pct >= 9.8).sum()),
            "limit_down": int((pct <= -9.8).sum()),
        }
    if "amount" in spot.columns:
        amt = pd.to_numeric(spot["amount"], errors="coerce").sum()
        breadth["total_amount_yi"] = round(float(amt) / 1e8, 1)
    return {"indices": indices, "breadth": breadth}


def _kline_daily(symbol: str, start_date: str, end_date: str,
                 adjust: str) -> tuple[pd.DataFrame, str]:
    """Fetch daily bars: sina first, EM fallback."""
    code6, mkt = normalize_symbol(symbol)
    sd = normalize_date(start_date, "20200101")
    ed = normalize_date(end_date, date.today().strftime("%Y%m%d"))
    errors = []
    try:
        df = ak.stock_zh_a_hist_sina(
            symbol=sina_symbol(code6, mkt), period="daily",
            start_date=sd, end_date=ed, adjust=adjust)
        if "turnover" in df.columns:
            df = df.copy()
            df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce") * 100
        return df, "sina"
    except Exception as e:
        errors.append(f"sina: {e}")
    try:
        df = ak.stock_zh_a_hist_em(
            symbol=code6, period="daily", start_date=sd, end_date=ed,
            adjust=adjust)
        return df, "em"
    except Exception as e:
        errors.append(f"em: {e}")
        raise RuntimeError("kline failed — " + " | ".join(errors))


def get_kline(symbol: str, period: str = "daily",
              start_date: str = "", end_date: str = "",
              adjust: str = "qfq") -> list[dict[str, Any]]:
    if period not in ("daily", "weekly", "monthly"):
        raise ValueError("period must be daily|weekly|monthly")
    if adjust not in ("", "qfq", "hfq"):
        raise ValueError("adjust must be ''|'qfq'|'hfq'")
    code6, _ = normalize_symbol(symbol)
    sd = normalize_date(start_date, "20200101")
    ed = normalize_date(end_date, date.today().strftime("%Y%m%d"))
    df = store.get_daily(
        code6, adjust, _iso(sd), _iso(ed),
        fetch=lambda s, e: _norm_kline(
            _kline_daily(symbol, s, e, adjust)[0], "daily"))
    df = _norm_kline(df, period)
    df["code"] = code6
    return df_records(df.reindex(columns=_KLINE_COLS))


def get_index_kline(symbol: str = "sh000001", period: str = "daily",
                    start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
    idx = _norm_index_symbol(symbol)
    sd = normalize_date(start_date, "20200101")
    ed = normalize_date(end_date, date.today().strftime("%Y%m%d"))
    df = store.get_daily(
        idx, "idx", _iso(sd), _iso(ed),
        fetch=lambda s, e: _norm_kline(ak.index_zh_daily_sina(symbol=idx), "daily"))
    df = _norm_kline(df, period)
    df["code"] = idx
    return df_records(df.reindex(columns=_KLINE_COLS))


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _is_index_symbol(symbol: str) -> bool:
    s = symbol.strip().lower()
    if not s.startswith(("sh", "sz", "bj")):
        return False
    d = s[2:8]
    return ((s.startswith("sh") and d.startswith("000"))
            or (s.startswith("sz") and d.startswith("399"))
            or (s.startswith("bj") and d.startswith(("8", "9"))))


def _intraday_points(df: pd.DataFrame, max_points: int) -> list[dict[str, Any]]:
    """Minute df (cols day/open/close/volume...) -> [{time, price, volume}]
    of the latest session, downsampled to <= max_points keeping the tail."""
    day = pd.to_datetime(df["day"], errors="coerce")
    last_day = day.dt.date.max()
    df = df.loc[day.dt.date == last_day]
    day = day.loc[day.dt.date == last_day]
    pts = [{"time": t.strftime("%H:%M"),
            "price": float(r["close"]),
            "volume": float(r.get("volume") or 0)}
           for t, (_, r) in zip(day, df.iterrows())]
    if len(pts) > max_points:
        stride = -(-len(pts) // (max_points - 1))
        last = pts[-1]
        pts = pts[::stride]
        if pts[-1]["time"] != last["time"]:
            pts.append(last)
    return pts


def get_intraday(symbol: str, max_points: int = 120) -> dict[str, Any]:
    """Latest-session 1-minute bars + prev_close.

    Returns {mode: "intraday"|"daily", prev_close, points:[{time,price,volume}]}.
    Stocks use Sina 1-min bars; indices try the same feed and fall back to
    the last 30 daily closes (mode="daily") when minute data is unavailable.
    """
    if _is_index_symbol(symbol):
        idx = _norm_index_symbol(symbol)
        try:
            df = ak.stock_zh_a_hist_min_sina(symbol=idx, period="1")
            if df is None or df.empty:
                raise RuntimeError("empty")
            session = _minute_session_date(df)
            daily = get_index_kline(idx)[-60:]
            prev = _close_before(daily, session)
            return {"symbol": idx, "mode": "intraday", "prev_close": prev,
                    "points": _intraday_points(df, max_points)}
        except Exception:
            daily = get_index_kline(idx)[-31:]
            pts = [{"time": b["date"], "price": b["close"],
                    "volume": b.get("volume") or 0} for b in daily[-30:]]
            prev = daily[0]["close"] if len(daily) > 30 else None
            return {"symbol": idx, "mode": "daily", "prev_close": prev,
                    "points": pts}

    code6, mkt = normalize_symbol(symbol)
    sina_sym = sina_symbol(code6, mkt)
    df = ak.stock_zh_a_hist_min_sina(symbol=sina_sym, period="1")
    if df is None or df.empty:
        raise KeyError(f"no minute data for {code6}")
    session = _minute_session_date(df)
    daily = get_kline(code6, adjust="", start_date="")[-60:]
    prev = _close_before(daily, session)
    if prev is None:
        # no earlier daily bar in store/network — use the quote's prev_close
        # only when the quote refers to the same session
        try:
            q = get_quote(code6)
            if str(q.get("date") or "")[:10] == session:
                prev = q.get("prev_close")
        except Exception:
            pass
    if prev is None:
        raise KeyError(f"no daily data for {code6}")
    return {"symbol": code6, "mode": "intraday", "prev_close": prev,
            "points": _intraday_points(df, max_points)}


def _today_iso() -> str:
    return date.today().isoformat()


def _minute_session_date(df: pd.DataFrame) -> str:
    """Session date (YYYY-MM-DD) of the last 1-minute bar."""
    col = "day" if "day" in df.columns else df.columns[0]
    return str(df.iloc[-1][col])[:10]


def _close_before(daily: list[dict[str, Any]], session_date: str) -> float | None:
    """Close of the last daily bar strictly before the intraday session date."""
    before = [b for b in daily if str(b.get("date") or "")[:10] < session_date]
    return float(before[-1]["close"]) if before else None


def get_limit_pool(date_str: str = "", pool: str = "zt",
                   limit: int = 300) -> list[dict[str, Any]]:
    fn_name = _LIMIT_POOL_FUNCS.get(pool)
    if fn_name is None:
        raise ValueError(f"pool must be one of {sorted(_LIMIT_POOL_FUNCS)}")
    d = normalize_date(date_str, date.today().strftime("%Y%m%d"))
    df = getattr(ak, fn_name)(date=d)
    return df_records(df, limit=limit)


def get_money_flow(symbol: str, days: int = 20) -> list[dict[str, Any]]:
    code6, mkt = normalize_symbol(symbol)
    market = "bj" if mkt == "bj" else mkt
    df = ak.stock_fund_flow_individual_hist_em(symbol=code6, market=market)
    cols = [c for c in _MONEY_FLOW_COLS if c in df.columns]
    df = df[cols].tail(max(1, min(int(days), 120)))
    if "日期" in df.columns:
        df = df.rename(columns={"日期": "date"})
    return df_records(df)


def get_financial_abstract(symbol: str, indicator: str = "按报告期",
                           limit: int = 12) -> list[dict[str, Any]]:
    code6, mkt = normalize_symbol(symbol)
    df = ak.stock_financial_analysis_indicator_em(
        symbol=ts_code(code6, mkt), indicator=indicator)
    return df_records(df, limit=max(1, min(int(limit), 40)))


def get_financial_statement(symbol: str, statement: str = "income",
                            limit: int = 12) -> list[dict[str, Any]]:
    code6, mkt = normalize_symbol(symbol)
    cn = _STATEMENT_MAP.get(statement)
    if cn is None:
        raise ValueError(f"statement must be one of {sorted(_STATEMENT_MAP)}")
    df = ak.stock_financial_report_sina(
        symbol=sina_symbol(code6, mkt), indicator=cn)
    return df_records(df, limit=max(1, min(int(limit), 40)))


# ---------------- events & factors ----------------

_CAL_TTL = 24 * 3600.0
_EARNINGS_FUNCS = {
    "yjbb": "stock_yjbb_em",   # 业绩报表 (年报/季报实际披露数据)
    "yjyg": "stock_yjyg_em",   # 业绩预告
    "yysj": "stock_yysj_em",   # 业绩快报
}


def get_earnings_calendar(report_date: str = "", kind: str = "yjbb",
                          limit: int = 300) -> list[dict[str, Any]]:
    """Earnings reports for a quarter-end report date (YYYYMMDD, e.g. 20250930).

    kind: "yjbb" 业绩报表 | "yjyg" 业绩预告 | "yysj" 业绩快报.
    Note: full-market crawl (~30-60 s); results cached for 24 h.
    """
    fn_name = _EARNINGS_FUNCS.get(kind)
    if fn_name is None:
        raise ValueError(f"kind must be one of {sorted(_EARNINGS_FUNCS)}")
    d = normalize_date(report_date, "20250930")
    df = _cached(f"earn_{kind}_{d}", _CAL_TTL,
                 lambda: getattr(ak, fn_name)(date=d))
    return df_records(df, limit=max(1, min(int(limit), 2000)))


_NOTICE_COLS = {
    "代码": "code", "名称": "name", "公告标题": "title",
    "公告类型": "type", "发布时间": "published_at", "地址": "url",
    "公告日期": "published_at",
}


def get_announcements(symbol: str = "", date_str: str = "",
                      limit: int = 100) -> list[dict[str, Any]]:
    """Exchange announcements for a single trading day (or one stock)."""
    d = normalize_date(date_str, date.today().strftime("%Y%m%d"))
    df = ak.stock_notice_report(symbol="全部", date=d)
    df = df.rename(columns={k: v for k, v in _NOTICE_COLS.items()
                            if k in df.columns})
    if symbol.strip():
        code6, _ = normalize_symbol(symbol)
        code_col = next((c for c in df.columns if "code" in str(c).lower()
                         or "代码" in str(c)), None)
        if code_col is not None:
            df = df[df[code_col].astype(str).str.contains(code6)]
    return df_records(df, limit=max(1, min(int(limit), 500)))


def get_factor_snapshot(symbol: str, days: int = 250) -> dict[str, Any]:
    """Quick factor snapshot from daily bars: momentum, volatility,
    MA position, turnover, and beta vs CSI-300."""
    code6, _ = normalize_symbol(symbol)
    days = max(60, min(int(days), 750))
    sd = (date.today() - pd.Timedelta(days=int(days * 1.8))).strftime("%Y%m%d")
    ed = date.today().strftime("%Y%m%d")
    df, _src = _kline_daily(symbol, sd, ed, "qfq")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values("date").tail(days).reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume", "amount", "turnover",
              "amplitude"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    close = df["close"]
    ret = close.pct_change()

    def _ret(n: int) -> float | None:
        if len(close) <= n:
            return None
        return round(float(close.iloc[-1] / close.iloc[-n - 1] - 1), 4)

    out: dict[str, Any] = {
        "code": code6, "name": _name_of(code6), "bars": len(df),
        "last_close": round(float(close.iloc[-1]), 3),
        "ret_20d": _ret(20), "ret_60d": _ret(60), "ret_120d": _ret(120),
        "vol_20d_ann": round(float(ret.tail(20).std() * np.sqrt(252)), 4)
        if len(ret.dropna()) >= 15 else None,
        "avg_turnover_20d": round(float(df["turnover"].tail(20).mean()), 3)
        if "turnover" in df.columns else None,
        "avg_amplitude_20d": round(float(df["amplitude"].tail(20).mean()), 3)
        if "amplitude" in df.columns else None,
    }
    for w in (5, 20, 60, 120):
        if len(close) >= w:
            ma = float(close.rolling(w).mean().iloc[-1])
            out[f"ma{w}"] = round(ma, 3)
            out[f"vs_ma{w}_pct"] = round((float(close.iloc[-1]) / ma - 1) * 100, 2)

    # beta vs CSI-300 over last ~120 aligned days
    try:
        idx = ak.index_zh_daily_sina(symbol="sh000300")
        idx["date"] = pd.to_datetime(idx["date"]).dt.strftime("%Y-%m-%d")
        m = df.merge(idx[["date", "close"]], on="date", suffixes=("", "_idx"))
        if len(m) > 60:
            m = m.tail(120)
            rs = m["close"].pct_change().dropna()
            ri = m["close_idx"].pct_change().dropna()
            if len(rs) > 30 and float(ri.var()) > 0:
                out["beta_120d"] = round(float(rs.cov(ri) / ri.var()), 3)
    except Exception:
        pass
    return out
