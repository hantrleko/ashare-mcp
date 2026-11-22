"""Equal-weight / inverse-volatility multi-stock portfolio backtest.

Rebalances on the first trading day of each week/month/quarter using
weights computed from data up to the previous close; orders execute at
that day's open (sells first).  Symbols without a bar on a date are not
tradable (suspended / not yet listed): they keep their position, are
valued at their last close, and receive no orders.  A-share lot size,
fees, slippage and limit-up/down blocking mirror the single-stock engine.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from ..data.facade import market_data
from .engine import _name_of
from ..utils import normalize_date, normalize_symbol
from .engine import (_buy_fee, _limit_of, _metrics,
                     _monthly_returns, _sell_fee)

WEIGHTINGS = ("equal", "inverse_vol")
REBALANCES = ("W", "M", "Q")


def _fetch_bars(code6: str, sd: str, ed: str) -> pd.DataFrame | None:
    try:
        raw, _ = market_data.call("get_kline", code6, period="daily",
                                  start_date=sd, end_date=ed, adjust="qfq")
        df = pd.DataFrame(raw)
        if df.empty:
            return None
        df["date"] = pd.to_datetime(df["date"])
        for c in ("open", "close"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["open", "close"])
        return df[["date", "open", "close"]] if len(df) else None
    except Exception:
        return None


def run_portfolio_backtest(symbols: list[str], weighting: str = "equal",
                           rebalance: str = "M", start_date: str = "",
                           end_date: str = "", capital: float = 1_000_000.0,
                           slippage_bps: float = 0.0,
                           min_trade_value: float = 5000.0,
                           benchmark: str = "sh000300") -> dict[str, Any]:
    if weighting not in WEIGHTINGS:
        raise ValueError(f"weighting must be one of {WEIGHTINGS}")
    if rebalance not in REBALANCES:
        raise ValueError(f"rebalance must be one of {REBALANCES}")
    seen: dict[str, None] = {}
    for s in symbols:
        code6, _ = normalize_symbol(s)
        seen[code6] = None
    codes = list(seen)
    if not 2 <= len(codes) <= 50:
        raise ValueError(f"需要 2–50 只不重复股票（收到 {len(codes)}）")

    sd = normalize_date(start_date, "20200101")
    ed = normalize_date(end_date, date.today().strftime("%Y%m%d"))

    with ThreadPoolExecutor(max_workers=4) as ex:
        fetched = list(ex.map(lambda c: _fetch_bars(c, sd, ed), codes))
    frames = {c: f for c, f in zip(codes, fetched) if f is not None
              and len(f) >= 5}
    skipped_symbols = [c for c in codes if c not in frames]
    if len(frames) < 2:
        raise ValueError(
            f"区间内有效数据不足 2 只（{len(frames)}，跳过 {skipped_symbols}）")

    braw, _ = market_data.call("get_index_kline", benchmark, period="daily",
                               start_date=sd, end_date=ed)
    bdf = pd.DataFrame(braw)
    if bdf.empty:
        raise RuntimeError(f"no index kline for {benchmark} in {sd}-{ed}")
    bdf["date"] = pd.to_datetime(bdf["date"])
    bdf["close"] = pd.to_numeric(bdf["close"], errors="coerce")
    bdf = bdf.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)

    # trading calendar = benchmark dates; per-symbol opens/closes on it
    cal = bdf["date"].tolist()
    cal_set = set(cal)
    opens: dict[str, dict[pd.Timestamp, float]] = {}
    closes: dict[str, dict[pd.Timestamp, float]] = {}
    rets: dict[str, dict[pd.Timestamp, float]] = {}
    for c, f in frames.items():
        f = f[f["date"].isin(cal_set)].sort_values("date")
        opens[c] = dict(zip(f["date"], f["open"]))
        closes[c] = dict(zip(f["date"], f["close"]))
        rets[c] = dict(zip(f["date"], f["close"].pct_change()))

    # first trading day of each W/M/Q group (+ day 0) = rebalance days
    periods = pd.Series(cal).dt.to_period(rebalance)
    reb_days = {i for i in range(len(cal))
                if i == 0 or periods.iloc[i] != periods.iloc[i - 1]}

    slip = float(slippage_bps) / 10000.0
    mtv = float(min_trade_value)
    limits = {c: _limit_of(c) for c in frames}
    names = {c: _name_of(c) for c in frames}

    cash = float(capital)
    shares: dict[str, int] = {c: 0 for c in frames}
    avg_cost: dict[str, float] = {c: 0.0 for c in frames}
    last_close: dict[str, float] = {c: float("nan") for c in frames}
    trades: list[dict[str, Any]] = []
    blocked = 0
    turnover = 0.0
    n_reb = 0
    reb_log: list[dict[str, Any]] = []
    equity = pd.Series(index=range(len(cal)), dtype=float)
    invested: dict[str, float] = {c: 0.0 for c in frames}   # buy cost - sell proceeds
    fees_paid: dict[str, float] = {c: 0.0 for c in frames}

    # first bar date per symbol: a symbol is only eligible for weight once
    # it has history before the rebalance day (handles late listings)
    first_date = {c: min(closes[c]) for c in frames}

    def target_weights(i: int) -> dict[str, float]:
        """Weights from data up to the previous close, over symbols that
        have any history by then."""
        prev_days = cal[:i]  # strictly before today
        prev_day = prev_days[-1] if prev_days else None
        # only symbols tradable today (bar present) and — after day 0 —
        # with history before today get weight
        eligible = [c for c in frames
                    if cal[i] in opens[c]
                    and (i == 0 or first_date[c] <= prev_day)]
        if not eligible:
            return {}
        if weighting == "equal":
            return {c: 1.0 / len(eligible) for c in eligible}
        # inverse_vol: w ∝ 1/std of last 60 daily returns (need >=20);
        # symbols without enough returns fall back to the mean score
        vols: dict[str, float] = {}
        for c in eligible:
            rs = [rets[c][d] for d in prev_days[-61:]
                  if d in rets[c] and np.isfinite(rets[c][d])]
            if len(rs) >= 20:
                v = float(np.std(rs))
                if v > 0:
                    vols[c] = v
        if not vols:
            return {c: 1.0 / len(eligible) for c in eligible}
        mean_vol = float(np.mean(list(vols.values())))
        inv = {c: 1.0 / vols.get(c, mean_vol) for c in eligible}
        tot = sum(inv.values())
        return {c: v / tot for c, v in inv.items()}

    for i, day in enumerate(cal):
        # update marks for symbols that trade today
        for c in frames:
            if day in closes[c]:
                last_close[c] = float(closes[c][day])

        if i in reb_days:
            tw = target_weights(i)
            prev_close_map = {}
            if i > 0:
                pday = cal[i - 1]
                for c in frames:
                    # close of the last bar at or before yesterday
                    pc = closes[c].get(pday)
                    if pc is None:
                        pc = next((closes[c][d] for d in reversed(cal[:i])
                                   if d in closes[c]), None)
                    prev_close_map[c] = pc
            def _prev_val(c: str) -> float:
                v = prev_close_map.get(c)
                if v is None:
                    v = last_close[c]
                return float(v) if np.isfinite(v) else 0.0
            eq_prev = cash + sum(shares[c] * _prev_val(c) for c in frames)
            n_reb += 1
            orders = 0
            day_turnover = 0.0

            # sells first: symbols whose target is below current value,
            # or that are held but get no target weight (untradable ones
            # keep their position — no bar today means no orders anyway)
            sell_plan: list[tuple[str, int]] = []
            buy_plan: list[tuple[str, int]] = []
            for c in frames:
                if day not in opens[c]:
                    continue  # suspended / not listed: no orders
                px = float(opens[c][day])
                tv = tw.get(c, 0.0) * eq_prev
                tgt = int(tv / px / 100) * 100 if px > 0 else 0
                # positions in symbols with no target weight are exited
                if c not in tw and shares[c] > 0:
                    tgt = 0
                diff = tgt - shares[c]
                if diff == 0:
                    continue
                if diff < 0:
                    sell_plan.append((c, diff))
                elif (shares[c] == 0 or abs(diff) * px >= mtv):
                    buy_plan.append((c, diff))

            for c, diff in sell_plan:
                px = float(opens[c][day])
                pc = prev_close_map.get(c)
                if (pc and limits[c] > 0
                        and px <= pc * (1 - limits[c]) + 0.005):
                    blocked += 1  # limit-down open: cannot sell
                    continue
                q = -diff
                exec_px = px * (1 - slip)
                amount = exec_px * q
                fee = _sell_fee(amount)
                cash += amount - fee
                shares[c] -= q
                invested[c] -= amount
                fees_paid[c] += fee
                turnover += amount
                day_turnover += amount
                orders += 1
                pnl = round((exec_px - avg_cost[c]) * q - fee, 2)
                if shares[c] <= 0:
                    shares[c] = 0
                    avg_cost[c] = 0.0
                trades.append({"date": day.strftime("%Y-%m-%d"),
                               "symbol": c, "side": "sell",
                               "price": round(exec_px, 4), "shares": q,
                               "amount": round(amount, 2),
                               "fee": round(fee, 2), "pnl": pnl})

            for c, diff in buy_plan:
                px = float(opens[c][day])
                pc = prev_close_map.get(c)
                if (pc and limits[c] > 0
                        and px >= pc * (1 + limits[c]) - 0.005):
                    blocked += 1  # limit-up open: cannot buy
                    continue
                exec_px = px * (1 + slip)
                q = diff
                if q * exec_px + _buy_fee(q * exec_px) > cash:
                    q = int((cash - _buy_fee(0)) / (exec_px * 100)) * 100
                if q <= 0:
                    continue
                amount = exec_px * q
                fee = _buy_fee(amount)
                if amount + fee > cash:
                    continue
                new_qty = shares[c] + q
                avg_cost[c] = ((avg_cost[c] * shares[c] + amount + fee)
                               / new_qty if new_qty else 0.0)
                cash -= amount + fee
                shares[c] = new_qty
                invested[c] += amount
                fees_paid[c] += fee
                turnover += amount
                day_turnover += amount
                orders += 1
                trades.append({"date": day.strftime("%Y-%m-%d"),
                               "symbol": c, "side": "buy",
                               "price": round(exec_px, 4), "shares": q,
                               "amount": round(amount, 2),
                               "fee": round(fee, 2)})

            reb_log.append({"date": day.strftime("%Y-%m-%d"),
                            "orders": orders,
                            "turnover": round(day_turnover, 2)})

        equity.iloc[i] = cash + sum(
            shares[c] * (last_close[c] if np.isfinite(last_close[c]) else 0.0)
            for c in frames)

    start_ts, end_ts = cal[0], cal[-1]
    years = max((end_ts - start_ts).days / 365.25, 1e-6)
    m = _metrics(equity, trades, capital, start_ts, end_ts)

    # benchmark normalized to initial capital
    bclose = bdf["close"].astype(float).reset_index(drop=True)
    bench_eq = bclose / float(bclose.iloc[0]) * capital
    bench_eq.index = equity.index[:len(bench_eq)]
    bm = _metrics(bench_eq, [], capital, start_ts, end_ts)
    avg_eq = float(equity.mean()) if len(equity) else capital

    # per-symbol contribution: realized + unrealized PnL net of fees
    contribution = []
    for c in frames:
        cur = shares[c] * (last_close[c] if np.isfinite(last_close[c]) else 0.0)
        pnl = cur - invested[c] - fees_paid[c]
        contribution.append({"code": c, "name": names.get(c, c),
                             "pnl": round(pnl, 2)})
    contribution.sort(key=lambda x: x["pnl"], reverse=True)

    final_value = float(equity.iloc[-1])
    holdings = []
    for c in frames:
        if shares[c] > 0 and np.isfinite(last_close[c]):
            v = shares[c] * last_close[c]
            holdings.append({"code": c, "name": names.get(c, c),
                             "shares": shares[c], "value": round(v, 2),
                             "weight": round(v / final_value, 4)
                             if final_value else None})
    holdings.sort(key=lambda x: x["value"], reverse=True)

    # downsampled equity curve with benchmark on the same calendar
    step = max(1, len(cal) // 400)
    idx = list(range(0, len(cal), step))
    if idx[-1] != len(cal) - 1:
        idx.append(len(cal) - 1)
    curve = [{"date": cal[i].strftime("%Y-%m-%d"),
              "equity": round(float(equity.iloc[i]), 2),
              "benchmark": round(float(bench_eq.iloc[i]), 2)}
             for i in idx]
    dfp = pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in cal]})

    notes = ["调仓在每周/月/季首个交易日开盘执行（信号取前一收盘）",
             "停牌/未上市个股当日不交易，按最近收盘价估值"]
    if skipped_symbols:
        notes.append(f"无区间数据已跳过：{', '.join(skipped_symbols)}")
    if blocked:
        notes.append(f"涨跌停价开盘无法成交，跳过 {blocked} 笔委托")

    return {
        "symbols": [c for c in codes if c in frames],
        "skipped_symbols": skipped_symbols,
        "weighting": weighting,
        "rebalance": rebalance,
        "benchmark": benchmark,
        "start": sd, "end": ed,
        "capital": capital,
        "bars": len(cal),
        **m,
        "benchmark_total_return": bm["total_return"],
        "benchmark_annual_return": bm["annual_return"],
        "benchmark_max_drawdown": bm["max_drawdown"],
        "excess_annual": round(m["annual_return"] - bm["annual_return"], 6),
        "annual_turnover": round(turnover / avg_eq / years, 4)
        if avg_eq else None,
        "num_rebalances": n_reb,
        "blocked_orders": blocked,
        "equity_curve": curve,
        "monthly_returns": _monthly_returns(dfp, equity),
        "contribution": contribution,
        "final_holdings": holdings,
        "rebalance_log": reb_log[-20:],
        "trades": trades[-200:],
        "notes": notes,
    }
