"""Built-in arena agents (内置选手) — deterministic rule strategies.

Three house agents trade a real PaperAccount through the normal
buy/sell path, so limits, T+1, fees and the arena replay all apply.

- house_trend 趋势跟踪 (weekly):  close > MA20 > MA60, rank by 20d return
- house_value 低估值   (monthly): 0 < PE<=15, 0 < PB<=1.5, rank by est. ROE
- house_momentum 动量  (weekly):  rank by 60d return

Plans are made after the close of day T when the NEXT trading day
starts a new ISO week (weekly) or month (monthly); they execute at the
first morning trigger tick (>=09:31) of that next trading day.  Plans
are persisted in ``paper.db.house_plans`` and both planning and
execution are idempotent unless ``force=True``.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd

from ..data import akshare_data as ad
from ..data import calendar as cal
from ..data.facade import market_data
from .accounts import AccountStore
from .paper import PaperAccount

log = logging.getLogger(__name__)

CAPITAL = 1_000_000.0
TOP_N = 10
UNIVERSE_N = 300
TRIM_BAND = 0.15          # trim when position value > target * (1+band)

AGENTS: dict[str, dict[str, str]] = {
    "house_trend": {
        "name": "趋势跟踪", "freq": "W", "strategy": "trend",
        "desc": "收盘价站上MA20且MA20>MA60，按20日涨幅取前10，周度调仓"},
    "house_value": {
        "name": "低估值", "freq": "M", "strategy": "value",
        "desc": "PE(TTM)≤15且PB≤1.5，按估算ROE取前10，月度调仓"},
    "house_momentum": {
        "name": "动量", "freq": "W", "strategy": "momentum",
        "desc": "按60日涨幅取前10，周度调仓"},
}

_DDL = """
CREATE TABLE IF NOT EXISTS house_plans(
  account_id TEXT NOT NULL,
  plan_date TEXT NOT NULL,
  exec_date TEXT,
  targets TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'planned',
  log TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY(account_id, plan_date));
"""


def _conn(store: AccountStore) -> sqlite3.Connection:
    conn = sqlite3.connect(store.path, timeout=30)
    conn.executescript(_DDL)
    return conn


# ---------------- persistence ----------------

def _save_plan(store: AccountStore, aid: str, plan: dict[str, Any]) -> None:
    with _conn(store) as c:
        c.execute(
            "INSERT OR REPLACE INTO house_plans"
            "(account_id, plan_date, exec_date, targets, status, log)"
            " VALUES (?,?,?,?,?,?)",
            (aid, plan["plan_date"], plan["exec_date"],
             json.dumps(plan["targets"], ensure_ascii=False),
             plan["status"],
             json.dumps(plan["log"], ensure_ascii=False)))


def _load_plan(store: AccountStore, aid: str,
               plan_date: str) -> dict[str, Any] | None:
    with _conn(store) as c:
        r = c.execute(
            "SELECT exec_date, targets, status, log FROM house_plans"
            " WHERE account_id=? AND plan_date=?",
            (aid, plan_date)).fetchone()
    if r is None:
        return None
    return {"plan_date": plan_date, "exec_date": r[0],
            "targets": json.loads(r[1]), "status": r[2],
            "log": json.loads(r[3])}


def latest_plan(store: AccountStore, aid: str,
                status: str | None = None) -> dict[str, Any] | None:
    q = ("SELECT plan_date, exec_date, targets, status, log"
         " FROM house_plans WHERE account_id=?")
    args: list[Any] = [aid]
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY plan_date DESC LIMIT 1"
    with _conn(store) as c:
        r = c.execute(q, args).fetchone()
    if r is None:
        return None
    return {"plan_date": r[0], "exec_date": r[1],
            "targets": json.loads(r[2]), "status": r[3],
            "log": json.loads(r[4])}


def plans_for(store: AccountStore, aid: str,
              limit: int = 5) -> list[dict[str, Any]]:
    with _conn(store) as c:
        rows = c.execute(
            "SELECT plan_date, exec_date, targets, status, log"
            " FROM house_plans WHERE account_id=?"
            " ORDER BY plan_date DESC LIMIT ?",
            (aid, int(limit))).fetchall()
    return [{"plan_date": r[0], "exec_date": r[1],
             "targets": json.loads(r[2]), "status": r[3],
             "log": json.loads(r[4])} for r in rows]


# ---------------- calendar ----------------

def _trading_days() -> list[str] | None:
    """Sorted trading-day list from the local calendar, or None."""
    try:
        days = cal._days()
        return days
    except Exception:
        return None


def _next_trading_day(today: date) -> date | None:
    days = _trading_days()
    if not days:
        return None
    iso = today.isoformat()
    nxt = next((d for d in days if d > iso), None)
    return date.fromisoformat(nxt) if nxt else None


def plan_due(freq: str, today: date) -> bool:
    """Plan after the close of `today` when the next trading day starts
    a new ISO week (W) or month (M).  Calendar-unknown fallback:
    W -> Friday, M -> last weekday of the month."""
    nxt = _next_trading_day(today)
    if nxt is None:
        if freq == "W":
            return today.weekday() == 4
        nxt = today + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        return nxt.month != today.month or nxt.year != today.year
    if freq == "W":
        return nxt.isocalendar()[:2] != today.isocalendar()[:2]
    return nxt.month != today.month or nxt.year != today.year


# ---------------- universe + signals ----------------

def _universe() -> pd.DataFrame:
    spot = ad._spot_df().copy()
    spot["code6"] = spot["code6"].astype(str).str[-6:]
    pe = pd.to_numeric(spot["pe_ttm"], errors="coerce")
    pb = pd.to_numeric(spot["pb"], errors="coerce")
    spot["pe_ttm"] = pe
    spot["pb"] = pb
    spot["roe_est"] = (pb / pe * 100).where((pb > 0) & (pe > 0))
    spot["price"] = pd.to_numeric(spot["price"], errors="coerce")
    spot["mkt_cap"] = pd.to_numeric(spot["mkt_cap"], errors="coerce")
    is_st = spot["name"].astype(str).str.upper().str.contains("ST")
    spot = spot[~is_st & spot["price"].notna() & (spot["price"] > 0)]
    return spot.nlargest(UNIVERSE_N, "mkt_cap")


def fetch_closes(codes: list[str],
                 get_kline: Callable | None = None) -> dict[str, list[float]]:
    """Daily qfq closes per code; failures yield an empty list."""
    get_kline = get_kline or (
        lambda s, **kw: market_data.call("get_kline", s, **kw))
    out: dict[str, list[float]] = {}
    for c in codes:
        try:
            bars, _ = get_kline(c, period="daily", adjust="qfq")
            out[c] = [float(b["close"]) for b in bars
                      if b.get("close") is not None]
        except Exception as e:
            log.debug("kline %s failed: %s", c, e)
            out[c] = []
    return out


def _ma(vals: list[float], n: int) -> float | None:
    return sum(vals[-n:]) / n if len(vals) >= n else None


def _ret(vals: list[float], n: int) -> float | None:
    if len(vals) < n + 1 or not vals[-n - 1]:
        return None
    return vals[-1] / vals[-n - 1] - 1


def _trend_targets(closes: dict[str, list[float]],
                   names: dict[str, str]) -> list[dict[str, Any]]:
    cands = []
    for c, v in closes.items():
        ma20, ma60 = _ma(v, 20), _ma(v, 60)
        r20 = _ret(v, 20)
        if ma20 and ma60 and r20 is not None \
                and len(v) >= 61 and v[-1] > ma20 > ma60:
            cands.append((c, r20))
    cands.sort(key=lambda x: x[1], reverse=True)
    return [
        {"code": c, "name": names.get(c, ""), "rank": i + 1,
         "metrics": {"ret20": round(r * 100, 2)},
         "note": f"周度调仓·趋势跟踪：站上MA20/MA60，20日涨幅 "
                 f"{r * 100:+.1f}%（第{i + 1}/{TOP_N}）"}
        for i, (c, r) in enumerate(cands[:TOP_N])
    ]


def _momentum_targets(closes: dict[str, list[float]],
                      names: dict[str, str]) -> list[dict[str, Any]]:
    cands = [(c, _ret(v, 60)) for c, v in closes.items()]
    cands = [(c, r) for c, r in cands if r is not None]
    cands.sort(key=lambda x: x[1], reverse=True)
    return [
        {"code": c, "name": names.get(c, ""), "rank": i + 1,
         "metrics": {"ret60": round(r * 100, 2)},
         "note": f"周度调仓·动量：60日涨幅 "
                 f"{r * 100:+.1f}%（第{i + 1}/{TOP_N}）"}
        for i, (c, r) in enumerate(cands[:TOP_N])
    ]


def _value_targets(spot: pd.DataFrame) -> list[dict[str, Any]]:
    df = spot[(spot["pe_ttm"] > 0) & (spot["pe_ttm"] <= 15)
              & (spot["pb"] > 0) & (spot["pb"] <= 1.5)]
    df = df.sort_values("roe_est", ascending=False, na_position="last")
    df = df[df["roe_est"].notna()].head(TOP_N)
    return [
        {"code": r.code6, "name": str(r.name), "rank": i + 1,
         "metrics": {"pe_ttm": round(float(r.pe_ttm), 2),
                     "pb": round(float(r.pb), 2),
                     "roe_est": round(float(r.roe_est), 2)},
         "note": f"月度调仓·低估值：PE {r.pe_ttm:.1f} PB {r.pb:.2f} "
                 f"估算ROE {r.roe_est:.1f}%（第{i + 1}/{TOP_N}）"}
        for i, r in enumerate(df.itertuples())
    ]


# ---------------- price-only rules preview (look-ahead-safe) ----------------

PREVIEW_FILE = "arena_preview.json"
PREVIEW_DAYS = 120
_preview_thread = None


def _dated_closes(code: str,
                  get_kline: Callable | None = None) -> dict[str, float]:
    get_kline = get_kline or (
        lambda s, **kw: market_data.call("get_kline", s, **kw))
    try:
        bars, _ = get_kline(code, period="daily", adjust="qfq")
    except Exception as e:
        log.debug("preview kline %s failed: %s", code, e)
        return {}
    return {str(b["date"])[:10]: float(b["close"]) for b in bars
            if b.get("close") is not None}


def _series_upto(pairs: list[tuple[str, float]], t: str) -> list[float]:
    """Closes on dates <= t (the no-look-ahead truncation)."""
    import bisect
    dates = [d for d, _ in pairs]
    i = bisect.bisect_right(dates, t)
    return [v for _, v in pairs[:i]]


def _close_le(pairs: list[tuple[str, float]], t: str) -> float | None:
    import bisect
    dates = [d for d, _ in pairs]
    i = bisect.bisect_right(dates, t) - 1
    return pairs[i][1] if i >= 0 else None


def _weekly_rebalance_dates(dates: list[str]) -> list[str]:
    """Last trading date of each ISO week, in order."""
    weeks: dict[tuple[int, int], str] = {}
    for d in dates:
        iso = date.fromisoformat(d).isocalendar()[:2]
        if iso not in weeks or d > weeks[iso]:
            weeks[iso] = d
    return sorted(weeks.values())


def _nav_stats(nav: list[float]) -> dict[str, float]:
    peak, mdd = nav[0], 0.0
    for v in nav:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return {"total": round(nav[-1] - 1, 4), "max_dd": round(mdd, 4)}


def preview_backtest(
        universe: list[str] | None = None,
        names: dict[str, str] | None = None,
        get_kline: Callable | None = None,
        get_index_kline: Callable | None = None,
        window_days: int = PREVIEW_DAYS) -> dict[str, Any]:
    """Weekly-rebalanced NAV for the two price-only house rules
    (trend, momentum) vs CSI 300, over the last ``window_days``
    trading days.  Equal weight, no costs.  The signal uses only
    closes <= the rebalance date and the position is entered at the
    next trading date's close, so there is no look-ahead and no
    same-bar fill.
    """
    get_kline = get_kline or (
        lambda s, **kw: market_data.call("get_kline", s, **kw))
    get_index_kline = get_index_kline or (
        lambda s, **kw: market_data.call("get_index_kline", s, **kw))
    if universe is None:
        uni = _universe()
        universe = [str(c) for c in uni["code6"]]
        names = {str(r.code6): str(r.name) for r in uni.itertuples()}
    names = names or {}

    ibars, _ = get_index_kline("sh000300", period="daily")
    bench = [(str(b["date"])[:10], float(b["close"])) for b in ibars
             if b.get("close")]
    all_dates = [d for d, _ in bench]
    window = set(all_dates[-window_days:])
    rebs = [d for d in _weekly_rebalance_dates(all_dates) if d in window]
    if len(rebs) < 2:
        raise ValueError("预览区间不足")

    # Signal at the close of rebalance date t (closes <= t), but the
    # position is only entered at the close of the NEXT trading date —
    # same convention as the backtest engine (signal at close, fill next
    # day), so a jump on the signal day itself is not captured.
    import bisect as _bs

    def _day_after(d: str) -> str | None:
        i = _bs.bisect_right(all_dates, d)
        return all_dates[i] if i < len(all_dates) else None

    periods: list[tuple[str, str, str]] = []  # (signal_date, entry, exit)
    for k in range(len(rebs)):
        t = rebs[k]
        entry = _day_after(t)
        if entry is None:
            break
        nxt_reb = rebs[k + 1] if k + 1 < len(rebs) else None
        exit_ = (_day_after(nxt_reb) if nxt_reb is not None
                 else None) or all_dates[-1]
        if exit_ <= entry:
            continue
        periods.append((t, entry, exit_))
    if not periods:
        raise ValueError("预览区间不足")

    series: dict[str, list[tuple[str, float]]] = {}
    for c in universe:
        dc = _dated_closes(c, get_kline)
        if dc:
            series[c] = sorted(dc.items())

    def nav_for(rule) -> tuple[list[float], list[dict[str, Any]]]:
        nav = [1.0]
        last_targets: list[dict[str, Any]] = []
        for t, entry, exit_ in periods:
            closes = {c: _series_upto(pairs, t)
                      for c, pairs in series.items()}
            last_targets = rule(closes, names)
            rets = []
            for tgt in last_targets:
                c = tgt["code"]
                p0 = _close_le(series.get(c, []), entry)
                p1 = _close_le(series.get(c, []), exit_)
                if p0 and p1:
                    rets.append(p1 / p0 - 1)
            nav.append(nav[-1] * (1 + (sum(rets) / len(rets)
                                       if rets else 0.0)))
        return nav, last_targets

    trend_nav, trend_latest = nav_for(_trend_targets)
    mom_nav, mom_latest = nav_for(_momentum_targets)
    bench_nav = [1.0]
    for t, entry, exit_ in periods:
        p0 = _close_le(bench, entry) or _close_le(bench, t)
        p1 = _close_le(bench, exit_) or p0
        bench_nav.append(bench_nav[-1] * (p1 / p0 if p0 else 1.0))
    out_dates = [periods[0][1]] + [x for _, _, x in periods]
    return {
        "days": window_days,
        "dates": out_dates,
        "series": {
            "trend": [round(v, 4) for v in trend_nav],
            "momentum": [round(v, 4) for v in mom_nav],
            "bench": [round(v, 4) for v in bench_nav],
        },
        "stats": {
            "trend": _nav_stats(trend_nav),
            "momentum": _nav_stats(mom_nav),
            "bench": _nav_stats(bench_nav),
        },
        "latest": {"trend": trend_latest, "momentum": mom_latest},
        "value_note": "低估值需实盘运行（无历史估值数据，无法回测）",
        "caption": "周末收盘后选股、下一交易日收盘价成交、等权、未计交易"
                   "成本；股票池为当前市值前300，存在幸存者偏差和前视偏"
                   "差。仅用于了解规则特点。",
    }


def _preview_path():
    from ..config import data_dir
    return data_dir() / PREVIEW_FILE


def preview_cached() -> dict[str, Any] | None:
    """Cached preview computed today, or None."""
    try:
        rec = json.loads(_preview_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if rec.get("date") == _cn_today() else None


def _cn_today() -> str:
    """CN-local date, same source as the scheduler/calendar."""
    return cal._cn_now().date().isoformat()


def compute_preview() -> dict[str, Any]:
    """Run the preview backtest and cache it per trading date."""
    payload = preview_backtest()
    rec = {"date": _cn_today(), **payload}
    _preview_path().write_text(json.dumps(rec, ensure_ascii=False),
                               encoding="utf-8")
    return rec


def preview_status() -> dict[str, Any]:
    rec = preview_cached()
    if rec is not None:
        return {"state": "ready", **rec}
    if _preview_thread is not None and _preview_thread.is_alive():
        return {"state": "running"}
    return {"state": "missing"}


def start_preview() -> None:
    """Kick off a background preview compute (idempotent)."""
    global _preview_thread
    if _preview_thread is not None and _preview_thread.is_alive():
        return

    def _run() -> None:
        try:
            compute_preview()
            log.info("arena preview computed")
        except Exception:
            log.exception("arena preview failed")
    import threading
    _preview_thread = threading.Thread(target=_run, daemon=True,
                                       name="ashare-arena-preview")
    _preview_thread.start()


# ---------------- plan / execute ----------------

def _store_or_default(store: AccountStore | None) -> AccountStore:
    return store or AccountStore()


def run_plan(aid: str, today: date | None = None, force: bool = False,
             store: AccountStore | None = None,
             closes: dict[str, list[float]] | None = None,
             spot: pd.DataFrame | None = None) -> dict[str, Any]:
    """Compute and persist today's plan for one house agent."""
    store = _store_or_default(store)
    meta = AGENTS[aid]
    today = today or date.today()
    pdate = today.isoformat()
    if not force and _load_plan(store, aid, pdate) is not None:
        return _load_plan(store, aid, pdate)  # idempotent

    spot = spot if spot is not None else _universe()
    names = dict(zip(spot["code6"], spot["name"].astype(str)))
    if meta["strategy"] == "value":
        targets = _value_targets(spot)
    else:
        if closes is None:
            closes = fetch_closes(spot["code6"].tolist())
        targets = (_trend_targets if meta["strategy"] == "trend"
                   else _momentum_targets)(closes, names)

    nxt = _next_trading_day(today)
    if nxt is None:                     # fallback: next weekday
        nxt = today + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
    plan = {"account_id": aid, "strategy": meta["strategy"],
            "plan_date": pdate, "exec_date": nxt.isoformat(),
            "targets": targets, "status": "planned", "log": []}
    _save_plan(store, aid, plan)
    return plan


def execute_plan(aid: str, plan: dict[str, Any],
                 acct: PaperAccount) -> dict[str, Any]:
    """Run the orders for a plan through the normal paper engine.
    Failures are appended to plan['log'], never raised."""
    logs: list[dict[str, Any]] = list(plan.get("log") or [])
    try:
        equity = float(acct.status().get("equity") or 0)
    except Exception as e:
        logs.append({"action": "status", "error": str(e)})
        plan["log"] = logs
        return plan
    target_val = equity / TOP_N
    positions = dict(acct.state.get("positions") or {})
    tgt_codes = {t["code"] for t in plan["targets"]}

    # sells first: exit names no longer targeted, trim overweight ones
    for code, pos in sorted(positions.items()):
        tgt = next((t for t in plan["targets"] if t["code"] == code), None)
        avail = int(pos.get("available") or 0)
        if tgt is None:
            if avail <= 0:
                logs.append({"action": "sell", "code": code,
                             "error": "T+1 无可卖"})
                continue
            try:
                acct.sell(code, avail, reason="调出：不再满足入选条件")
                logs.append({"action": "sell", "code": code,
                             "shares": avail, "ok": True})
            except Exception as e:
                logs.append({"action": "sell", "code": code,
                             "error": str(e)})
            continue
        try:
            px, _prev, _n = acct._quote(code)
            value = pos["shares"] * px
            excess = value - target_val
            trim = int(excess / px / 100) * 100
            if excess > target_val * TRIM_BAND and trim > 0:
                sell_n = min(trim, avail)
                if sell_n <= 0:
                    logs.append({"action": "trim", "code": code,
                                 "error": "T+1 无可卖"})
                else:
                    acct.sell(code, sell_n, reason="调仓：减持至目标权重")
                    logs.append({"action": "trim", "code": code,
                                 "shares": sell_n, "ok": True})
        except Exception as e:
            logs.append({"action": "trim", "code": code,
                         "error": str(e)})

    # buys: fill underweight targets to equity/10, 100-share lots
    for t in plan["targets"]:
        code = t["code"]
        try:
            px, _prev, _n = acct._quote(code)
            pos = acct.state.get("positions", {}).get(code) or {}
            held_val = pos.get("shares", 0) * px
            gap = target_val - held_val
            shares = int(gap / px / 100) * 100
            if shares <= 0:
                continue
            acct.buy(code, shares, reason=t["note"])
            logs.append({"action": "buy", "code": code,
                         "shares": shares, "ok": True})
        except Exception as e:
            logs.append({"action": "buy", "code": code,
                         "error": str(e)})
    plan["log"] = logs
    return plan


def run_execute(aid: str, today: date | None = None, force: bool = False,
                store: AccountStore | None = None,
                acct: PaperAccount | None = None) -> dict[str, Any] | None:
    """Execute the latest 'planned' plan whose exec_date <= today."""
    store = _store_or_default(store)
    today = today or date.today()
    if force:
        plan = latest_plan(store, aid)
    else:
        plan = latest_plan(store, aid, status="planned")
    if plan is None or (not force and
                        (plan["exec_date"] or "9999") > today.isoformat()):
        return None
    acct = acct or PaperAccount(aid, store)
    plan = execute_plan(aid, plan, acct)
    plan["status"] = "executed"
    _save_plan(store, aid, plan)
    return plan


# ---------------- orchestration ----------------

def house_ids(store: AccountStore | None = None) -> list[str]:
    store = _store_or_default(store)
    existing = {a["id"] for a in store.list()}
    return [a for a in AGENTS if a in existing]


def enable(store: AccountStore | None = None,
           today: date | None = None) -> dict[str, Any]:
    """Create any missing house accounts and make an immediate plan."""
    store = _store_or_default(store)
    today = today or date.today()
    existing = {a["id"] for a in store.list()}
    created = []
    for aid, meta in AGENTS.items():
        if aid not in existing:
            store.create(meta["name"], CAPITAL, account_id=aid,
                         kind="house", model="规则策略", arena=True)
            created.append(aid)
    plans = run_plans(today, force=True, store=store)
    return {"created": created, "agents": list(AGENTS),
            "plans": plans}


def run_plans(today: date, force: bool = False,
              store: AccountStore | None = None,
              universe: pd.DataFrame | None = None,
              closes: dict[str, list[float]] | None = None,
              due_only: bool = False) -> dict[str, Any]:
    """Plan every enabled house agent due today.

    Weekly strategies share one kline fetch over the universe."""
    store = _store_or_default(store)
    ids = house_ids(store)
    out: dict[str, Any] = {}
    spot = closes_want = None
    for aid in ids:
        freq = AGENTS[aid]["freq"]
        strat = AGENTS[aid]["strategy"]
        if due_only and not plan_due(freq, today):
            continue
        if universe is None:
            universe = _universe()
        spot = universe
        if strat != "value" and closes_want is None:
            closes_want = closes if closes is not None else \
                fetch_closes(spot["code6"].tolist())
        out[aid] = run_plan(aid, today, force=force, store=store,
                            closes=closes_want, spot=spot)
    return out


def run_executes(today: date, force: bool = False,
                 store: AccountStore | None = None,
                 acct_fn: Callable[[str], PaperAccount] | None = None
                 ) -> dict[str, Any]:
    """Execute every house plan due today."""
    store = _store_or_default(store)
    out = {}
    for aid in house_ids(store):
        res = run_execute(aid, today, force=force, store=store,
                          acct=acct_fn(aid) if acct_fn else None)
        if res is not None:
            out[aid] = res
    return out


def settle_hook(today: date, store: AccountStore | None = None) -> None:
    """Called inside settle_tick after equity recording: plan agents
    whose next trading day opens a new week/month."""
    try:
        run_plans(today, store=store, due_only=True)
    except Exception as e:
        log.warning("house plan hook failed: %s", e)


def trigger_hook(now_hhmm: str, today: date,
                 store: AccountStore | None = None,
                 acct_fn: Callable[[str], PaperAccount] | None = None
                 ) -> None:
    """Called from trigger_tick: at/after 09:31 execute due plans."""
    if now_hhmm < "09:31":
        return
    try:
        run_executes(today, store=store, acct_fn=acct_fn)
    except Exception as e:
        log.warning("house execute hook failed: %s", e)
