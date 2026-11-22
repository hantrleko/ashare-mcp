"""Daily-bar backtest engine.

Execution model: signals are computed on day *t* close and executed at
day *t+1* open (no look-ahead). Long-only, weight in [0, 1] of equity.
Costs mirror A-share rules: commission 0.025% (min 5), stamp tax 0.05%
on sells, transfer fee 0.001%, plus optional slippage in bps.
"""
from __future__ import annotations

from datetime import date
from itertools import product
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..data.facade import market_data
from ..trading.paper import COMMISSION_MIN, COMMISSION_RATE, STAMP_TAX_SELL, TRANSFER_FEE
from ..utils import limit_pct_for, normalize_date, normalize_symbol

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
    # default bounds come from a calibration window at the START of the
    # sample (no look-ahead); explicit lower/upper bypass it entirely
    calib = max(5, int(p.get("calib", 60)))
    win = df.iloc[:calib]
    lo = float(lo) if lo else float(win["low"].min()) * 0.98
    hi = float(hi) if hi else float(win["high"].max()) * 1.02
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


def _monthly_returns(df: pd.DataFrame, equity: pd.Series) -> list[dict[str, Any]]:
    """Month-over-month equity returns from the full daily series."""
    s = pd.Series(equity.values, index=pd.to_datetime(df["date"]))
    month_last = s.resample("ME").last().dropna()
    prev = month_last.shift(1)
    out = []
    for i, (ts, v) in enumerate(month_last.items()):
        base = prev.iloc[i] if i > 0 else float(s.iloc[0])
        out.append({"month": ts.strftime("%Y-%m"),
                    "ret": round((v / base - 1) * 100, 3)})
    return out


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

    df, source = _load_bars(symbol, sd, ed, adjust)
    weight = _BUILDERS[strategy](df, params)
    slip = float(slippage_bps) / 10000.0
    # buy_hold = enter once, never rebalance; the deadband skips all dust trades
    mtv = float("inf") if strategy == "buy_hold" else float(min_trade_value)
    limit = _limit_of(code6)

    # target[i] is applied at day i's open (signal from day i-1's close)
    equity, trades, blocked = _simulate(df, weight.shift(1), capital,
                                      slip, mtv, limit)
    notes: list[str] = []
    if strategy == "grid" and (not params.get("lower") or not params.get("upper")):
        notes.append(
            f"网格上下沿自动取自前{int(params.get('calib', 60))}根校准K线")
    if blocked:
        notes.append(f"涨跌停价开盘无法成交，跳过 {blocked} 笔委托")

    m = _metrics(equity, trades, capital, df["date"].iloc[0], df["date"].iloc[-1])
    return {
        "symbol": code6,
        "strategy": strategy,
        "params": params,
        "source": source,
        "start": sd, "end": ed,
        "capital": capital,
        "bars": len(df),
        "blocked_orders": blocked,
        "notes": notes,
        **m,
        "equity_curve": _downsample_curve(df, equity),
        "monthly_returns": _monthly_returns(df, equity),
        "trades": trades[-100:],
    }


def _load_bars(symbol: str, sd: str, ed: str,
               adjust: str = "qfq") -> tuple[pd.DataFrame, str]:
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
    return df, source


def _name_of(code6: str) -> str:
    """Name from the bundled stock list (offline, fast) — used only for
    ST-limit detection, so a slightly stale name is fine."""
    try:
        from ..data.akshare_data import _bundled_stock_list
        df = _bundled_stock_list()
        hit = df[df["code6"] == code6]
        return str(hit.iloc[0]["name"]) if len(hit) else ""
    except Exception:
        return ""


def _limit_of(code6: str) -> float:
    # current name is used for the ST 5% limit — an approximation of
    # historical ST status, which we do not track
    return limit_pct_for(code6, _name_of(code6))


def _simulate(df: pd.DataFrame, target: pd.Series, capital: float,
              slip: float, mtv: float, limit_pct: float = 0.0,
              first_prev_close: float | None = None,
              ) -> tuple[pd.Series, list[dict[str, Any]], int]:
    """Trade at each day's open toward ``target[i]`` weight, mark at close.

    ``target[i]`` is the desired equity weight at day i's open (normally the
    signal from the previous close).  For the first bar the reference equity
    is ``capital`` and the limit check uses ``first_prev_close`` if given.
    Returns (equity, trades, blocked_orders).
    """
    cash = float(capital)
    shares = 0
    avg_cost = 0.0
    trades: list[dict[str, Any]] = []
    blocked = 0
    equity = pd.Series(index=df.index, dtype=float)
    target = target.reset_index(drop=True)

    for i in range(len(df)):
        row = df.iloc[i]
        w = float(target.iloc[i]) if i < len(target) else 0.0
        if not np.isfinite(w):
            w = 0.0
        w = min(max(w, 0.0), 1.0)
        if i == 0:
            eq_prev = float(capital)
            prev_close = first_prev_close
        else:
            prev_close = float(df.iloc[i - 1]["close"])
            eq_prev = cash + shares * prev_close

        px = float(row["open"])
        target_val = w * eq_prev
        target_shares = int(target_val / px / 100) * 100 if px > 0 else 0
        diff = target_shares - shares
        # deadband: skip dust trades; always allow entering from flat
        # and full exit (target 0)
        if diff and (target_shares == 0 or shares == 0
                     or abs(diff) * px >= mtv):
            buy = diff > 0
            if prev_close is not None and limit_pct > 0:
                if buy and px >= prev_close * (1 + limit_pct) - 0.005:
                    blocked += 1  # cannot buy at a limit-up open
                    diff = 0
                elif not buy and px <= prev_close * (1 - limit_pct) + 0.005:
                    blocked += 1  # cannot sell at a limit-down open
                    diff = 0
            if diff > 0:
                exec_px = px * (1 + slip)
                amount = exec_px * diff
                fee = _buy_fee(amount)
                if amount + fee > cash:
                    affordable = int((cash - _buy_fee(0))
                                     / (exec_px * 100)) * 100
                    diff = max(0, affordable - shares)
                    if diff > 0:
                        amount = exec_px * diff
                        fee = _buy_fee(amount)
                total = amount + fee
                if diff > 0 and total <= cash:
                    new_qty = shares + diff
                    avg_cost = ((avg_cost * shares + total) / new_qty
                                if new_qty else 0.0)
                    cash -= total
                    shares = new_qty
                    trades.append({"date": row["date"].strftime("%Y-%m-%d"),
                                   "side": "buy", "price": round(exec_px, 4),
                                   "shares": diff, "amount": round(amount, 2),
                                   "fee": round(fee, 2)})
            elif diff < 0:
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
        # mark-to-market at close AFTER any execution that day
        equity.iloc[i] = cash + shares * float(row["close"])

    return equity, trades, blocked


# ---------------- parameter scan ----------------

_SCAN_PARAMS: dict[str, set[str]] = {
    "ma_cross": {"fast", "slow"},
    "momentum": {"lookback", "threshold"},
    "grid": {"grids", "calib"},
}
_SCAN_METRICS = ("sharpe", "total_return", "annual_return", "max_drawdown")
_SCAN_FIELDS = ("total_return", "annual_return", "sharpe",
                "max_drawdown", "num_trades")


def _scan_score(m: dict, metric: str) -> float:
    v = float(m.get(metric) or 0.0)
    # for drawdown "best" = closest to zero (least negative)
    return v


def scan_backtest(symbol: str, strategy: str, grid: dict[str, list[float]],
                  start_date: str = "", end_date: str = "",
                  split: float = 0.7, metric: str = "sharpe",
                  capital: float = 1_000_000.0,
                  slippage_bps: float = 0.0,
                  min_trade_value: float = 5000.0) -> dict[str, Any]:
    """In-sample / out-of-sample grid scan over one strategy's params."""
    if strategy not in _SCAN_PARAMS:
        raise ValueError(
            f"scan supports {sorted(_SCAN_PARAMS)} (not buy_hold)")
    if metric not in _SCAN_METRICS:
        raise ValueError(f"metric must be one of {_SCAN_METRICS}")
    bad = set(grid) - _SCAN_PARAMS[strategy]
    if bad:
        raise ValueError(f"invalid param(s) for {strategy}: {sorted(bad)}")
    if not grid:
        raise ValueError("grid must not be empty")
    keys = sorted(grid)
    values = [[float(v) for v in grid[k]] for k in keys]
    combos = [dict(zip(keys, vs)) for vs in product(*values)]
    if len(combos) > 100:
        raise ValueError(f"{len(combos)} 组参数超过上限 100")

    code6, _ = normalize_symbol(symbol)
    sd = normalize_date(start_date, "20200101")
    ed = normalize_date(end_date, date.today().strftime("%Y%m%d"))
    df, source = _load_bars(symbol, sd, ed, "qfq")
    sp = int(len(df) * float(split))
    if sp < 60 or len(df) - sp < 60:
        raise ValueError(
            f"样本内/外各需至少 60 根K线（共 {len(df)}，split={split}）")

    slip = float(slippage_bps) / 10000.0
    mtv = float(min_trade_value)
    limit = _limit_of(code6)

    df_is = df.iloc[:sp].reset_index(drop=True)
    df_oos = df.iloc[sp:].reset_index(drop=True)

    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for combo in combos:
        if (strategy == "ma_cross"
                and combo.get("fast", 0) >= combo.get("slow", 0)):
            skipped.append(combo)
            continue
        weight = _BUILDERS[strategy](df, combo)
        target = weight.shift(1).reset_index(drop=True)
        # grid bounds calibrate on the first `calib` bars of the IN-SAMPLE
        # window; for OOS runs _w_grid uses the same full-series build so
        # the bounds stay those of the IS calibration
        eq_is, tr_is, _ = _simulate(df_is, target.iloc[:sp], capital,
                                    slip, mtv, limit)
        eq_oos, tr_oos, _ = _simulate(
            df_oos, target.iloc[sp:], capital, slip, mtv, limit,
            first_prev_close=float(df["close"].iloc[sp - 1]))
        m_is = _metrics(eq_is, tr_is, capital,
                        df_is["date"].iloc[0], df_is["date"].iloc[-1])
        m_oos = _metrics(eq_oos, tr_oos, capital,
                         df_oos["date"].iloc[0], df_oos["date"].iloc[-1])
        results.append({
            "params": {k: (int(v) if float(v).is_integer() else v)
                       for k, v in combo.items()},
            "is": {k: m_is[k] for k in _SCAN_FIELDS},
            "oos": {k: m_oos[k] for k in _SCAN_FIELDS},
        })
    if not results:
        raise ValueError("所有参数组合均被跳过")

    best = max(results, key=lambda r: _scan_score(r["is"], metric))
    oos_ranked = sorted(results, key=lambda r: _scan_score(r["oos"], metric),
                        reverse=True)
    rank = next(i for i, r in enumerate(oos_ranked, 1)
                if r["params"] == best["params"])

    out: dict[str, Any] = {
        "symbol": code6,
        "strategy": strategy,
        "metric": metric,
        "source": source,
        "start": sd, "end": ed,
        "split": split,
        "split_date": df["date"].iloc[sp].strftime("%Y-%m-%d"),
        "bars": len(df),
        "capital": capital,
        "results": results,
        "skipped": skipped,
        "best_is": {"params": best["params"],
                    "is": best["is"], "oos": best["oos"]},
        "oos_rank_of_best_is": rank,
        "num_combos": len(results),
        "notes": ["样本内最优参数不代表样本外表现；以样本外为准"],
    }
    if len(keys) == 2:
        out["axes"] = {"names": keys,
                       "values": {k: sorted(set(values[j]))
                                  for j, k in enumerate(keys)}}
    return out
