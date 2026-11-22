"""tushare data source — fallback provider (requires TUSHARE_TOKEN)."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ..config import tushare_token
from ..utils import (
    latest_records,
    df_records,
    normalize_date,
    normalize_symbol,
    resample_ohlcv,
    ts_code,
)

_pro = None


def _client():
    global _pro
    if _pro is None:
        token = tushare_token()
        if not token:
            raise RuntimeError("TUSHARE_TOKEN env var is not set")
        import tushare as ts

        ts.set_token(token)
        _pro = ts.pro_api()
    return _pro


def _norm_kline(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={
        "trade_date": "date", "vol": "volume", "pct_chg": "pct_chg",
        "pre_close": "prev_close",
    })
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce") * 100  # 手 -> 股
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000  # 千元 -> 元
    if "date" in df.columns:
        df["date"] = df["date"].astype(str).str.replace("-", "")
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    if period != "daily":
        df = resample_ohlcv(df, period)
    keep = [c for c in ("date", "open", "high", "low", "close", "volume",
                        "amount", "pct_chg", "prev_close", "change") if c in df.columns]
    return df[keep].sort_values("date").reset_index(drop=True)


def search_stock(query: str, limit: int = 10) -> list[dict[str, Any]]:
    pro = _client()
    df = pro.stock_basic(exchange="", list_status="L",
                         fields="ts_code,symbol,name,market")
    q = str(query).strip()
    q_digits = "".join(ch for ch in q if ch.isdigit())
    mask = df["name"].astype(str).str.contains(q, na=False)
    if q_digits:
        mask |= df["symbol"].astype(str).str.contains(q_digits, na=False)
    hits = df[mask].head(limit)
    out = []
    for _, r in hits.iterrows():
        code6 = str(r["symbol"])
        out.append({
            "code": code6,
            "name": str(r["name"]),
            "market": str(r.get("market", "")).lower() or code6[:1],
            "ts_code": str(r["ts_code"]),
        })
    return out


def get_quote(symbol: str) -> dict[str, Any]:
    """Best-effort realtime: tushare has no free tick, returns latest daily bar."""
    code6, mkt = normalize_symbol(symbol)
    pro = _client()
    df = pro.daily(ts_code=ts_code(code6, mkt), limit=1)
    if df is None or df.empty:
        raise KeyError(f"no daily data for {ts_code(code6, mkt)}")
    r = df.iloc[0]
    return {
        "code": code6,
        "name": "",
        "price": float(r["close"]),
        "pct_chg": float(r.get("pct_chg") or 0),
        "date": str(r["trade_date"]),
        "volume": float(r.get("vol") or 0) * 100,
        "amount": float(r.get("amount") or 0) * 1000,
        "prev_close": float(r.get("pre_close") or 0),
        "note": "latest daily close (tushare has no free realtime quotes)",
    }


def get_kline(symbol: str, period: str = "daily",
              start_date: str = "", end_date: str = "",
              adjust: str = "qfq") -> list[dict[str, Any]]:
    code6, mkt = normalize_symbol(symbol)
    pro = _client()
    sd = normalize_date(start_date, "20200101")
    ed = normalize_date(end_date, date.today().strftime("%Y%m%d"))
    df = pro.daily(ts_code=ts_code(code6, mkt), start_date=sd, end_date=ed)
    return df_records(_norm_kline(df, period))


def get_index_kline(symbol: str = "sh000001", period: str = "daily",
                    start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
    s = symbol.strip().lower()
    digits = "".join(ch for ch in s if ch.isdigit())[-6:]
    if s.startswith("sz") or digits.startswith("399"):
        tsc = f"{digits}.SZ"
    else:
        tsc = f"{digits}.SH"
    pro = _client()
    sd = normalize_date(start_date, "20200101")
    ed = normalize_date(end_date, date.today().strftime("%Y%m%d"))
    df = pro.index_daily(ts_code=tsc, start_date=sd, end_date=ed)
    return df_records(_norm_kline(df, period))


def get_financial_abstract(symbol: str, indicator: str = "按报告期",
                           limit: int = 12) -> list[dict[str, Any]]:
    code6, mkt = normalize_symbol(symbol)
    pro = _client()
    df = pro.fina_indicator(ts_code=ts_code(code6, mkt),
                            start_date="", end_date="")
    return latest_records(df, max(1, min(int(limit), 40)))


def get_financial_statement(symbol: str, statement: str = "income",
                            limit: int = 12) -> list[dict[str, Any]]:
    code6, mkt = normalize_symbol(symbol)
    pro = _client()
    fn_map = {
        "income": pro.income,
        "balance": pro.balancesheet,
        "cashflow": pro.cashflow,
    }
    fn = fn_map.get(statement)
    if fn is None:
        raise ValueError(f"statement must be one of {sorted(fn_map)}")
    df = fn(ts_code=ts_code(code6, mkt), start_date="", end_date="")
    return latest_records(df, max(1, min(int(limit), 40)))


def get_money_flow(symbol: str, days: int = 20) -> list[dict[str, Any]]:
    code6, mkt = normalize_symbol(symbol)
    pro = _client()
    ed = date.today().strftime("%Y%m%d")
    sd = (date.today() - pd.Timedelta(days=int(days) * 2 + 30)).strftime("%Y%m%d")
    df = pro.moneyflow(ts_code=ts_code(code6, mkt), start_date=sd, end_date=ed)
    return df_records(df, limit=max(1, min(int(days), 120)))
