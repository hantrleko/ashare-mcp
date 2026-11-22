"""Agent arena — leaderboard and agent detail over paper accounts.

Arena accounts are ordinary paper accounts flagged ``arena=1`` (plus a
``kind``/``model`` label).  Metrics use one Tencent batch quote for all
held symbols (falling back to average cost when quotes fail), the
recorded daily equity history plus a live point for today, and the
benchmark index over each account's own active window.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np

from ..data import tencent
from ..data.facade import market_data
from ..utils import normalize_symbol
from .accounts import AccountStore
from .paper import PaperAccount


def _arena_accounts(store: AccountStore) -> list[dict[str, Any]]:
    return [a for a in store.list() if a.get("arena")]


def _live_prices(codes: list[str]) -> dict[str, float]:
    """One Tencent batch for every held symbol; {} on failure."""
    if not codes:
        return {}
    try:
        syms = [normalize_symbol(c) for c in codes]
        df = tencent.fetch_quotes([f"{m}{c}" for c, m in syms])
        if df.empty:
            return {}
        out = {}
        for _, r in df.iterrows():
            px = float(r.get("price") or 0)
            code = "".join(ch for ch in str(r.get("code", "")) if ch.isdigit())
            if np.isfinite(px) and px > 0 and code:
                out[code] = px
        return out
    except Exception:
        return {}


def _bench_series(benchmark: str, start: str) -> list[tuple[str, float]]:
    try:
        raw, _ = market_data.call("get_index_kline", benchmark,
                                  period="daily", start_date=start)
        return [(str(b["date"])[:10], float(b["close"])) for b in raw
                if b.get("close")]
    except Exception:
        return []


def _anchor(bench: list[tuple[str, float]], created: str
            ) -> tuple[str, float] | None:
    """Benchmark anchor for an account created on ``created``: the last
    close on or before that date (non-trading days roll back)."""
    pts = [(d, v) for d, v in bench if d <= created]
    return pts[-1] if pts else None


def _agent_metrics(acct: PaperAccount, live: dict[str, float],
                   bench: list[tuple[str, float]]) -> dict[str, Any]:
    st = acct.state
    init = float(st.get("initial_capital") or 0)
    cash = float(st.get("cash") or 0)
    positions = st.get("positions") or {}
    mv = 0.0
    for code6, pos in positions.items():
        px = live.get(code6, float(pos.get("avg_cost") or 0))
        mv += px * pos["shares"]
    equity = cash + mv

    hist = [h for h in (st.get("history") or []) if h.get("equity")]
    series = [(h["date"], float(h["equity"])) for h in hist]
    today = date.today().isoformat()
    if not series or series[-1][0] != today:
        series = series + [(today, equity)]
    else:
        series[-1] = (today, equity)
    # seed a flat initial point at creation so the series starts on the
    # same anchor the benchmark is normalized to
    created = str(st.get("created_at") or "")[:10]
    if created and init and series[0][0] > created:
        series.insert(0, (created, init))

    ret = equity / init - 1 if init else 0.0
    eq = np.array([v for _, v in series], dtype=float)
    peak = np.maximum.accumulate(eq) if len(eq) else np.array([1.0])
    mdd = float((eq / peak - 1).min()) if len(eq) else 0.0
    sharpe = None
    if len(eq) >= 10:
        d = np.diff(eq) / eq[:-1]
        if d.std() > 0:
            sharpe = round(float(d.mean() / d.std() * math.sqrt(252)), 4)

    orders = st.get("orders") or []
    sells = [o for o in orders if o.get("side") == "sell"
             and o.get("status") == "filled"]
    wins = sum(1 for o in sells if (o.get("realized_pnl") or 0) > 0)
    turnover = sum(float(o.get("amount") or 0) for o in orders
                   if o.get("status") == "filled")
    last_trade = max((o.get("time") or "" for o in orders), default="") or None
    days_active = max((date.today() - date.fromisoformat(created)).days, 0) \
        if created else 0

    excess = None
    if bench and created:
        anc = _anchor(bench, created)
        if anc and anc[1] > 0:
            b_ret = bench[-1][1] / anc[1] - 1
            excess = round(ret - b_ret, 6)

    return {
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "initial_capital": init,
        "return": round(ret, 6),
        "excess": excess,
        "max_drawdown": round(mdd, 6),
        "sharpe": sharpe,
        "num_trades": len([o for o in orders if o.get("status") == "filled"]),
        "win_rate": round(wins / len(sells), 4) if sells else None,
        "turnover": round(turnover, 2),
        "last_trade_at": last_trade,
        "days_active": days_active,
        "position_count": len(positions),
        "series": [{"date": d, "equity": round(v, 2)} for d, v in series],
        "positions": positions,
    }


def leaderboard(benchmark: str = "sh000300",
                store: AccountStore | None = None) -> dict[str, Any]:
    store = store or AccountStore()
    agents = _arena_accounts(store)
    # one batch quote for all held symbols across all agents
    held: set[str] = set()
    states = {}
    for a in agents:
        acct = PaperAccount(a["id"], store)
        states[a["id"]] = acct
        held.update((acct.state.get("positions") or {}).keys())
    live = _live_prices(sorted(held))
    bench = _bench_series(benchmark, "20200101")

    # trim the benchmark to the earliest agent's anchor date so the
    # overlay chart doesn't span years before any agent existed
    anchors = [
        _anchor(bench, str(acct.state.get("created_at") or "")[:10])
        for acct in states.values()]
    anchor_dates = [a[0] for a in anchors if a]
    start = min(anchor_dates) if anchor_dates else None
    bench = [(d, v) for d, v in bench if start and d >= start]

    rows = []
    series = {}
    for a in agents:
        m = _agent_metrics(states[a["id"]], live, bench)
        series[a["id"]] = m["series"]
        rows.append({
            "id": a["id"], "name": a["name"], "model": a.get("model", ""),
            "created_at": a.get("created_at"),
            **{k: v for k, v in m.items()
               if k not in ("series", "positions")},
        })
    rows.sort(key=lambda r: r["return"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"as_of": datetime.now().isoformat(timespec="seconds"),
            "benchmark": benchmark, "agents": rows,
            "series": series,
            "bench_series": [{"date": d, "close": v} for d, v in bench]}


def agent_detail(account_id: str, benchmark: str = "sh000300",
                 store: AccountStore | None = None) -> dict[str, Any]:
    store = store or AccountStore()
    meta = next((a for a in _arena_accounts(store) if a["id"] == account_id),
                None)
    if meta is None:
        raise KeyError(f"unknown arena agent {account_id!r}")
    acct = PaperAccount(account_id, store)
    st = acct.state
    live = _live_prices(sorted((st.get("positions") or {}).keys()))
    bench = _bench_series(benchmark, "20200101")
    m = _agent_metrics(acct, live, bench)

    # benchmark normalized to initial capital at the agent's anchor
    # (last close on or before created_at); flat until the first
    # trading day after creation
    init = m["initial_capital"] or 1.0
    created = str(st.get("created_at") or "")[:10]
    anc = _anchor(bench, created) if bench and created else None
    bench = [(d, v) for d, v in bench if not anc or d >= anc[0]]
    series = []
    for pt in m["series"]:
        b = next((v for d, v in reversed(bench) if d <= pt["date"]), None)
        series.append({
            "date": pt["date"], "equity": pt["equity"],
            "benchmark": round(b / anc[1] * init, 2)
            if b and anc and anc[1] > 0 else None,
        })

    positions = []
    for code6, pos in (st.get("positions") or {}).items():
        px = live.get(code6, float(pos.get("avg_cost") or 0))
        mv = round(px * pos["shares"], 2)
        cost = round(pos["avg_cost"] * pos["shares"], 2)
        positions.append({
            "code": code6, "name": pos.get("name", ""),
            "shares": pos["shares"], "avg_cost": pos["avg_cost"],
            "last_price": round(px, 4), "market_value": mv,
            "pnl": round(mv - cost, 2),
        })
    trades = list(reversed(st.get("orders") or []))
    return {
        "id": account_id, "name": meta["name"], "model": meta.get("model", ""),
        "created_at": meta.get("created_at"),
        **{k: v for k, v in m.items() if k not in ("series", "positions")},
        "series": series,
        "positions": positions,
        "trades": trades,
        "benchmark": benchmark,
    }
