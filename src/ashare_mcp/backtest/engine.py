"""Daily-bar backtest engine.

Execution model: signals are computed on day *t* close and executed at
day *t+1* open (no look-ahead). Long-only, weight in [0, 1] of equity.
Costs mirror A-share rules: commission 0.025% (min 5), stamp tax 0.05%
on sells, transfer fee 0.001%, plus optional slippage in bps.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..data.facade import market_data
from ..trading.paper import COMMISSION_MIN, COMMISSION_RATE, STAMP_TAX_SELL, TRANSFER_FEE
from ..utils import normalize_date, normalize_symbol

STRATEGIES = ("buy_hold", "ma_cross", "momentum", "grid")


def _buy_fee(amount: float) -> float:
    return max(amount * COMMISSION_RATE, COMMISSION_MIN) + amount * TRANSFER_FEE


def _sell_fee(amount: float) -> float:
    return (max(amount * COMMISSION_RATE, COMMISSION_MIN)
            + amount * (STAMP_TAX_SELL + TRANSFER_FEE))


def _w_buy_hold(df: pd.DataFrame, p: dict) -> pd.Series:
    return pd.Series(1.0, index=df.index)


def _w_ma_cross(df: pd.DataFrame, p: dict) -> pd.Series:
    fast = int(p.get("fast", 5))
    slow = int(p.get("slow", 20))
    fma = df["close"].rolling(fast).mean()
    sma = df["close"].rolling(slow).mean()
    return (fma > sma).astype(float).fillna(0.0)


def _w_momentum(df: pd.DataFrame, p: dict) -> pd.Series:
    lb = int(p.get("lookback", 20))
    thr = float(p.get("threshold", 0.03))
    mom = df["close"].pct_change(lb)
    return (mom > thr).astype(float).fillna(0.0)


def _w_grid(df: pd.DataFrame, p: dict) -> pd.Series:
    n = max(2, int(p.get("grids", 10)))
    lo = p.get("lower")
    hi = p.get("upper")
    lo = float(lo) if lo else float(df["low"].min()) * 0.98
    hi = float(hi) if hi else float(df["high"].max()) * 1.02
    if hi <= lo:
        return pd.Series(0.0, index=df.index)
    g = ((df["close"] - lo) / (hi - lo) * n).clip(0, n)
    # at lo -> fully invested (n units), at hi -> flat (0 units)
    return (1 - g / n).clip(0, 1)


_BUILDERS: dict[str, Callable[[pd.DataFrame, dict], pd.Series]] = {
    "buy_hold": _w_buy_hold,
    "ma_cross": _w_ma_cross,
    "momentum": _w_momentum,
    "grid": _w_grid,
}


def _metrics(equity: pd.Series, trades: list[dict], capital: float,
             start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    final = float(equity.iloc[-1])
    years = max((end - start).days / 365.25, 1e-6)
    total_ret = final / capital - 1
    cagr = (final / capital) ** (1 / years) - 1 if final > 0 and capital > 0 else -1.0
    peak = equity.cummax()
    max_dd = float((equity / peak - 1).min())
    daily = equity.pct_change().dropna()
    sharpe = (float(daily.mean() / daily.std() * np.sqrt(252))
              if len(daily) > 1 and daily.std() > 0 else 0.0)
    sells = [t for t in trades if t["side"] == "sell" and "pnl" in t]
    wins = sum(1 for t in sells if t["pnl"] > 0)
    return {
        "final_equity": round(final, 2),
        "total_return": round(total_ret, 6),
        "annual_return": round(cagr, 6),
        "max_drawdown": round(max_dd, 6),
        "sharpe": round(sharpe, 4),
        "num_trades": len(trades),
        "num_sells": len(sells),
        "win_rate": round(wins / len(sells), 4) if sells else None,
    }


def _downsample_curve(df: pd.DataFrame, equity: pd.Series,
                      max_points: int = 400) -> list[dict[str, Any]]:
    step = max(1, len(df) // max_points)
    idx = list(range(0, len(df), step))
    if idx[-1] != len(df) - 1:
        idx.append(len(df) - 1)
    return [{"date": df["date"].iloc[i], "equity": round(float(equity.iloc[i]), 2)}
            for i in idx]


def run_backtest(symbol: str, strategy: str = "ma_cross",
                 params: dict | None = None,
                 start_date: str = "", end_date: str = "",
                 capital: float = 1_000_000.0, adjust: str = "qfq",
                 slippage_bps: float = 0.0,
                 min_trade_value: float = 5000.0) -> dict[str, Any]:
    if strategy not in _BUILDERS:
        raise ValueError(f"strategy must be one of {STRATEGIES}")
    params = params or {}
    code6, _ = normalize_symbol(symbol)
    sd = normalize_date(start_date, "20200101")
    ed = normalize_date(end_date, date.today().strftime("%Y%m%d"))

    raw, source = market_data.call(
        "get_kline", symbol, period="daily",
        start_date=sd, end_date=ed, adjust=adjust)
    df = pd.DataFrame(raw)
    if df.empty:
        raise RuntimeError(f"no kline data for {symbol} in {sd}-{ed}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "close"]).reset_index(drop=True)
    if len(df) < 30:
        raise RuntimeError(f"not enough bars ({len(df)}) for backtest")

    weight = _BUILDERS[strategy](df, params)
    slip = float(slippage_bps) / 10000.0
    # buy_hold = enter once, never rebalance; the deadband skips all dust trades
    mtv = float("inf") if strategy == "buy_hold" else float(min_trade_value)

    cash = float(capital)
    shares = 0
    avg_cost = 0.0
    trades: list[dict[str, Any]] = []
    equity = pd.Series(index=df.index, dtype=float)

    for i in range(len(df)):
        row = df.iloc[i]
        # mark-to-market at close of day i (before any execution that day)
        equity.iloc[i] = cash + shares * float(row["close"])
        if i == 0:
            continue
        # execute weight target from previous day's close at today's open
        w = float(weight.iloc[i - 1]) if i - 1 < len(weight) else 0.0
        if not np.isfinite(w):
            w = 0.0
        w = min(max(w, 0.0), 1.0)

        eq_prev = cash + shares * float(df.iloc[i - 1]["close"])
        px = float(row["open"])
        target_val = w * eq_prev
        target_shares = int(target_val / px / 100) * 100 if px > 0 else 0
        diff = target_shares - shares
        if diff == 0:
            continue
        # deadband: skip dust trades; always allow entering from flat
        # and full exit (target 0)
        if target_shares != 0 and shares != 0 and abs(diff) * px < mtv:
            continue

        if diff > 0:  # buy
            exec_px = px * (1 + slip)
            amount = exec_px * diff
            fee = _buy_fee(amount)
            if amount + fee > cash:
                affordable = int((cash - _buy_fee(0)) / (exec_px * 100)) * 100
                if affordable <= 0 or affordable == shares:
                    continue
                diff = affordable - shares
                if diff <= 0:
                    continue
                amount = exec_px * diff
                fee = _buy_fee(amount)
            total = amount + fee
            if total > cash:
                continue
            new_qty = shares + diff
            avg_cost = (avg_cost * shares + total) / new_qty if new_qty else 0.0
            cash -= total
            shares = new_qty
            trades.append({"date": row["date"].strftime("%Y-%m-%d"),
                           "side": "buy", "price": round(exec_px, 4),
                           "shares": diff, "amount": round(amount, 2),
                           "fee": round(fee, 2)})
        else:  # sell
            diff = -diff
            exec_px = px * (1 - slip)
            amount = exec_px * diff
            fee = _sell_fee(amount)
            proceeds = amount - fee
            pnl = round((exec_px - avg_cost) * diff - fee, 2)
            cash += proceeds
            shares -= diff
            if shares <= 0:
                shares = 0
                avg_cost = 0.0
            trades.append({"date": row["date"].strftime("%Y-%m-%d"),
                           "side": "sell", "price": round(exec_px, 4),
                           "shares": diff, "amount": round(amount, 2),
                           "fee": round(fee, 2), "pnl": pnl})

    # final mark at last close already in equity.iloc[-1]
    m = _metrics(equity, trades, capital, df["date"].iloc[0], df["date"].iloc[-1])
    return {
        "symbol": code6,
        "strategy": strategy,
        "params": params,
        "source": source,
        "start": sd, "end": ed,
        "capital": capital,
        "bars": len(df),
        **m,
        "equity_curve": _downsample_curve(df, equity),
        "trades": trades[-100:],
    }
