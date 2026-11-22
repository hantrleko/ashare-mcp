"""Single-factor / composite backtests over a daily close panel.

Universe: top-N by current mkt_cap (top_cap) or a custom symbol list.
Factors are computed point-in-time on the panel; IC / RankIC, quantile
NAVs, long-short, top-group turnover and IC decay are reported.
"""
from __future__ import annotations

import math
import threading
import time
import uuid
from collections import OrderedDict
from datetime import date, timedelta
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..data import akshare_data as ad
from ..data.facade import market_data
from ..utils import normalize_symbol

FACTOR_INFO: list[dict[str, Any]] = [
    {"id": "mom_20", "name": "20日动量", "sign": 1,
     "desc": "close/close(t-20)-1，追涨短期强者"},
    {"id": "mom_60", "name": "60日动量", "sign": 1,
     "desc": "close/close(t-60)-1"},
    {"id": "mom_120_skip20", "name": "120日动量(剔近20日)", "sign": 1,
     "desc": "close(t-20)/close(t-120)-1，剔除短期反转"},
    {"id": "rev_5", "name": "5日反转", "sign": 1,
     "desc": "-(close/close(t-5)-1)，买入近5日超跌"},
    {"id": "vol_20", "name": "20日波动率", "sign": -1,
     "desc": "近20日日收益std(≥15日)，低波动异象取负向"},
    {"id": "vol_60", "name": "60日波动率", "sign": -1,
     "desc": "近60日日收益std(≥45日)"},
    {"id": "turn_20", "name": "20日换手率", "sign": -1,
     "desc": "近20日平均换手率(≥15日)，低换手取正向暴露"},
    {"id": "amihud_20", "name": "Amihud非流动性", "sign": 1,
     "desc": "mean(|r|/成交额)×1e8(≥15日)，非流动性溢价"},
    {"id": "maxret_20", "name": "20日最大日收益", "sign": -1,
     "desc": "近20日最大单日涨幅(≥15日)，彩票效应取负向"},
]
FACTOR_IDS = {f["id"] for f in FACTOR_INFO}

MIN_BARS = 130          # drop symbols with fewer total bars
MIN_STOCKS = 20         # drop rebalance dates with fewer included stocks
WARMUP_DAYS = 200       # calendar days of extra history before `start`
JOB_TTL = 3600.0
RESULT_CACHE = 10
MAX_QUEUED = 3
DECAY_LAGS = 6

NOTE_TOP_CAP = ("股票池按当前市值选取，存在幸存者偏差与前视偏差"
                "（历史上未进入前N的股票被排除）")
NOTE_COST = "未计交易成本与冲击成本；收益为收盘价到收盘价，前复权"
NOTE_VALUATION = "估值类因子（PE/PB/市值）缺少时点数据，暂不提供"

# ---------------------------------------------------------------- panels

_lock = threading.Lock()
_panel_cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_result_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()


def _cached(store: OrderedDict, key: Any) -> Any:
    with _lock:
        hit = store.get(key)
        if hit and time.time() - hit[0] < JOB_TTL:
            store.move_to_end(key)
            return hit[1]
        store.pop(key, None)
    return None


def _put_cached(store: OrderedDict, key: Any, val: Any,
                cap: int = RESULT_CACHE) -> None:
    with _lock:
        store[key] = (time.time(), val)
        store.move_to_end(key)
        while len(store) > cap:
            store.popitem(last=False)


def _pick_universe(universe: str, universe_size: int,
                   symbols: list[str] | None) -> list[tuple[str, str]]:
    if universe == "custom":
        if not symbols:
            raise ValueError("custom universe 需要 symbols")
        codes = []
        seen = set()
        for s in symbols:
            code6, _ = normalize_symbol(s)
            if code6 not in seen:
                seen.add(code6)
                codes.append((code6, ""))
        if not 20 <= len(codes) <= 300:
            raise ValueError("symbols 数量需为 20–300")
        return codes
    if universe != "top_cap":
        raise ValueError("universe 须为 top_cap|custom")
    n = int(universe_size)
    if not 20 <= n <= 300:
        raise ValueError("universe_size 需为 20–300")
    spot = ad._spot_df().copy()
    spot["code6"] = spot["code6"].astype(str).str[-6:]
    spot["name"] = spot["name"].astype(str)
    spot = spot[~spot["name"].str.contains("ST", case=False, na=False)]
    price = pd.to_numeric(spot["price"], errors="coerce")
    cap = pd.to_numeric(spot["mkt_cap"], errors="coerce")
    spot = spot[(price > 0) & cap.notna() & (cap > 0)]
    spot = spot.assign(_cap=cap).sort_values("_cap", ascending=False)
    top = spot.head(n)
    return [(str(r.code6), str(r.name)) for r in top.itertuples()]


def _load_panel(univ: list[tuple[str, str]], start: str, end: str,
                progress: Callable[[int, int, str], None] | None
                ) -> dict[str, Any]:
    """Wide close/amount/turnover panels indexed by sh000300 dates."""
    codes = [c for c, _ in univ]
    key = (tuple(codes), start, end)
    hit = _cached(_panel_cache, key)
    if hit is not None:
        if progress:
            progress(len(codes), len(codes), "kline")
        return hit

    warm = (pd.Timestamp(start) - timedelta(days=WARMUP_DAYS)
            ).strftime("%Y-%m-%d")
    bench, _ = market_data.call("get_index_kline", "sh000300",
                                period="daily", start_date=warm,
                                end_date=end)
    idx = pd.DatetimeIndex(pd.to_datetime(
        [r["date"] for r in bench])).sort_values().unique()

    close = pd.DataFrame(index=idx)
    amount = pd.DataFrame(index=idx)
    turn = pd.DataFrame(index=idx)
    dropped: list[str] = []
    total = len(univ)
    for i, (code, _name) in enumerate(univ, 1):
        try:
            rows, _ = market_data.call(
                "get_kline", code, period="daily",
                start_date=warm, end_date=end, adjust="qfq")
            df = pd.DataFrame(rows)
        except Exception:
            df = pd.DataFrame()
        if len(df) < MIN_BARS:
            dropped.append(code)
        else:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").reindex(idx)
            close[code] = pd.to_numeric(df["close"], errors="coerce")
            amount[code] = pd.to_numeric(df["amount"], errors="coerce")
            turn[code] = pd.to_numeric(df["turnover"], errors="coerce")
        if progress:
            progress(i, total, "kline")
    panel = {"close": close, "amount": amount, "turnover": turn,
             "dropped": dropped}
    _put_cached(_panel_cache, key, panel, cap=6)
    return panel


# ---------------------------------------------------------------- factors

def factor_frame(name: str, close: pd.DataFrame, amount: pd.DataFrame,
                 turn: pd.DataFrame) -> pd.DataFrame:
    ret = close / close.shift(1) - 1
    if name == "mom_20":
        return close / close.shift(20) - 1
    if name == "mom_60":
        return close / close.shift(60) - 1
    if name == "mom_120_skip20":
        return close.shift(20) / close.shift(120) - 1
    if name == "rev_5":
        return -(close / close.shift(5) - 1)
    if name == "vol_20":
        return ret.rolling(20, min_periods=15).std(ddof=1)
    if name == "vol_60":
        return ret.rolling(60, min_periods=45).std(ddof=1)
    if name == "turn_20":
        return turn.rolling(20, min_periods=15).mean()
    if name == "amihud_20":
        illiq = (ret.abs() / amount).where(amount > 0)
        return illiq.rolling(20, min_periods=15).mean() * 1e8
    if name == "maxret_20":
        return ret.rolling(20, min_periods=15).max()
    raise ValueError(f"unknown factor: {name}")


def composite_frame(components: list[dict[str, Any]],
                    close: pd.DataFrame, amount: pd.DataFrame,
                    turn: pd.DataFrame) -> pd.DataFrame:
    """Mean of direction-adjusted cross-sectional percentile ranks."""
    if not components:
        raise ValueError("composite 需要至少一个因子")
    ranks = []
    for c in components:
        fid = c.get("factor")
        sign = int(c.get("sign", 1))
        if fid not in FACTOR_IDS:
            raise ValueError(f"unknown factor: {fid}")
        if sign not in (1, -1):
            raise ValueError("sign 须为 ±1")
        f = factor_frame(fid, close, amount, turn)
        r = f.rank(axis=1, pct=True)
        ranks.append(r if sign == 1 else 1 - r)
    mask = ranks[0].notna()
    for r in ranks[1:]:
        mask &= r.notna()
    mean = sum(ranks) / len(ranks)
    return mean.where(mask)


# ---------------------------------------------------------------- testing

def _rebalance_dates(idx: pd.DatetimeIndex, start: str, end: str,
                     freq: str) -> pd.DatetimeIndex:
    s = pd.Series(idx[(idx >= start) & (idx <= end)])
    if s.empty:
        raise ValueError("区间内无交易日")
    per = "W" if freq == "W" else "M"
    grouped = s.groupby(s.dt.to_period(per)).max()
    return pd.DatetimeIndex(grouped.values)


def _spearman(a: pd.Series, b: pd.Series) -> float:
    ra, rb = a.rank(), b.rank()
    n = len(ra)
    if n < 3 or ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(ra.corr(rb))


def _summary(vals: list[float], periods_per_year: int) -> dict[str, Any]:
    arr = np.array([v for v in vals if math.isfinite(v)])
    n = len(arr)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "icir": None,
                "icir_ann": None, "t": None, "pos_ratio": None}
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    icir = mean / std if std > 0 else None
    t = mean / (std / math.sqrt(n)) if std > 0 else None
    return {"n": n, "mean": mean, "std": std, "icir": icir,
            "icir_ann": icir * math.sqrt(periods_per_year)
            if icir is not None else None,
            "t": t,
            "pos_ratio": float((arr > 0).mean())}


def _validate(params: dict[str, Any]) -> None:
    """Cheap param validation (no data access)."""
    fid = params.get("factor", "mom_20")
    composite = params.get("composite")
    if composite:
        for c in composite:
            if c.get("factor") not in FACTOR_IDS:
                raise ValueError(f"unknown factor: {c.get('factor')}")
            if int(c.get("sign", 1)) not in (1, -1):
                raise ValueError("sign 须为 ±1")
    elif fid not in FACTOR_IDS:
        raise ValueError(f"unknown factor: {fid}")
    if str(params.get("freq", "M")).upper() not in ("W", "M"):
        raise ValueError("freq 须为 W|M")
    if not 3 <= int(params.get("quantiles", 5)) <= 10:
        raise ValueError("quantiles 需为 3–10")
    if params.get("universe", "top_cap") not in ("top_cap", "custom"):
        raise ValueError("universe 须为 top_cap|custom")
    start = params.get("start_date") or ""
    end = params.get("end_date") or ""
    if start and end and start >= end:
        raise ValueError("start_date 须早于 end_date")


def run_test(params: dict[str, Any],
             progress: Callable[[int, int, str], None] | None = None
             ) -> dict[str, Any]:
    """Full factor backtest; raises ValueError on bad params."""
    _validate(params)
    fid = params.get("factor", "mom_20")
    composite = params.get("composite")
    freq = str(params.get("freq", "M")).upper()
    q = int(params.get("quantiles", 5))
    today = date.today().isoformat()
    start = params.get("start_date") or (
        pd.Timestamp(today) - pd.DateOffset(years=3)
        ).strftime("%Y-%m-%d")
    end = params.get("end_date") or today

    if progress:
        progress(0, 1, "universe")
    univ = _pick_universe(params.get("universe", "top_cap"),
                          int(params.get("universe_size", 100)),
                          params.get("symbols"))
    panel = _load_panel(univ, start, end, progress)
    close, amount, turn = panel["close"], panel["amount"], panel["turnover"]

    if progress:
        progress(0, 1, "factor")
    if composite:
        f = composite_frame(composite, close, amount, turn)
        fname = "composite"
    else:
        if fid not in FACTOR_IDS:
            raise ValueError(f"unknown factor: {fid}")
        f = factor_frame(fid, close, amount, turn)
        fname = fid

    if progress:
        progress(0, 1, "test")
    rdates = _rebalance_dates(close.index, start, end, freq)
    if len(rdates) < 7:
        raise ValueError("可用调仓日不足（需 ≥6 个有效日期）")
    ppy = 52 if freq == "W" else 12

    # per-date cross-sections with forward returns to the next date
    dates_used: list[str] = []
    dates_small: list[str] = []
    ic_rows: list[dict[str, Any]] = []
    group_ret: dict[int, list[float]] = {i: [] for i in range(1, q + 1)}
    group_nav: dict[int, float] = {i: 1.0 for i in range(1, q + 1)}
    group_dates: list[str] = []
    ls_ret: list[float] = []
    members_top: set[str] | None = None
    turnovers: list[float] = []

    for k in range(len(rdates) - 1):
        t0, t1 = rdates[k], rdates[k + 1]
        fv = f.loc[t0]
        fwd = close.loc[t1] / close.loc[t0] - 1
        ok = fv.notna() & close.loc[t0].notna() & fwd.notna()
        fv, fwd = fv[ok], fwd[ok]
        if len(fv) < MIN_STOCKS:
            dates_small.append(t0.strftime("%Y-%m-%d"))
            continue
        dates_used.append(t0.strftime("%Y-%m-%d"))
        fw = fv.clip(fv.quantile(0.01), fv.quantile(0.99))
        ic = float(fw.corr(fwd)) if fw.std() > 0 and fwd.std() > 0 \
            else float("nan")
        ric = _spearman(fv, fwd)
        ic_rows.append({"date": t0.strftime("%Y-%m-%d"),
                        "ic": ic, "rank_ic": ric, "n": int(len(fv))})
        groups = pd.qcut(fv.rank(method="first"), q,
                         labels=list(range(1, q + 1)))
        rets = fwd.groupby(groups, observed=False).mean()
        # NAV points sit on the period END date (return realized at t1)
        group_dates.append(t1.strftime("%Y-%m-%d"))
        for i in range(1, q + 1):
            r = float(rets.get(i, float("nan")))
            r = 0.0 if not math.isfinite(r) else r
            group_ret[i].append(r)
            group_nav[i] *= 1 + r
        ls_ret.append(group_ret[q][-1] - group_ret[1][-1])
        cur = set(groups[groups == q].index)
        if members_top is not None and cur:
            turnovers.append(1 - len(cur & members_top) / len(cur))
        members_top = cur

    if len(dates_used) < 6:
        raise ValueError(
            f"有效调仓日不足（{len(dates_used)} < 6），请扩大区间或股票池")

    origin = {"date": dates_used[0], "nav": 1.0}
    quantile_nav = {
        f"Q{i}": [origin] + [{"date": d, "nav": round(float(v), 6)}
                             for d, v in zip(group_dates,
                                             np.cumprod([1 + r
                                                         for r in group_ret[i]]))]
        for i in range(1, q + 1)}
    ls_nav = np.cumprod([1 + r for r in ls_ret])
    quantile_nav["LS"] = [origin] + [{"date": d, "nav": round(float(v), 6)}
                                     for d, v in zip(group_dates, ls_nav)]

    nper = len(group_dates)
    quantile_annual = {
        f"Q{i}": (group_nav[i] ** (ppy / nper) - 1) if nper else None
        for i in range(1, q + 1)}
    ls_nav_end = float(ls_nav[-1]) if nper else 1.0
    quantile_annual["LS"] = (ls_nav_end ** (ppy / nper) - 1) if nper else None

    # IC decay: rank IC of f(t_k) vs the L-th forward period
    decay: list[dict[str, Any]] = []
    for lag in range(1, DECAY_LAGS + 1):
        vals = []
        for k in range(len(rdates) - lag):
            t0, t1 = rdates[k], rdates[k + lag]
            fv = f.loc[t0]
            fwd = close.loc[t1] / close.loc[t0] - 1
            ok = fv.notna() & close.loc[t0].notna() & fwd.notna()
            fv, fwd = fv[ok], fwd[ok]
            if len(fv) < MIN_STOCKS:
                continue
            ric = _spearman(fv, fwd)
            if math.isfinite(ric):
                vals.append(ric)
        decay.append({"lag": lag,
                      "rank_ic_mean": float(np.mean(vals))
                      if vals else None,
                      "n": len(vals)})

    notes = []
    if params.get("universe", "top_cap") == "top_cap":
        notes.append(NOTE_TOP_CAP)
    notes += [NOTE_COST, NOTE_VALUATION]

    result = {
        "params": {"factor": fname, "composite": composite,
                   "universe": params.get("universe", "top_cap"),
                   "universe_size": int(params.get("universe_size", 100)),
                   "symbols": params.get("symbols"),
                   "start_date": start, "end_date": end,
                   "freq": freq, "quantiles": q},
        "universe": {"count": close.shape[1],
                     "dropped": panel["dropped"]},
        "dates_used": dates_used,
        "dates_dropped_small": dates_small,
        "ic_series": ic_rows,
        "ic_summary": _summary([r["ic"] for r in ic_rows], ppy),
        "rank_ic_summary": _summary([r["rank_ic"] for r in ic_rows], ppy),
        "quantile_nav": quantile_nav,
        "quantile_annual": quantile_annual,
        "top_turnover": (float(np.mean(turnovers))
                         if turnovers else None),
        "ic_decay": decay,
        "notes": notes,
    }
    return result


# ---------------------------------------------------------------- jobs


class FactorJobs:
    """Single-worker FIFO job runner with param-keyed result cache."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._queue: list[tuple[str, dict]] = []
        self._jobs: dict[str, dict[str, Any]] = {}
        self._worker: threading.Thread | None = None

    def submit(self, params: dict[str, Any]) -> str:
        norm = _norm_params(params)
        _validate(norm)
        job_id = uuid.uuid4().hex[:12]
        with self._cond:
            self._jobs[job_id] = {"state": "queued", "params": norm,
                                  "progress": {"loaded": 0, "total": 0,
                                               "stage": "queued"},
                                  "created": time.time(), "result": None,
                                  "error": None}
            if len(self._queue) >= MAX_QUEUED:
                del self._jobs[job_id]
                raise ValueError("队列已满")
            self._queue.append((job_id, norm))
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._loop, daemon=True)
                self._worker.start()
            self._cond.notify()
        return job_id

    def status(self, job_id: str) -> dict[str, Any]:
        with self._cond:
            j = self._jobs.get(job_id)
            if j is None:
                raise ValueError("unknown job_id")
            return {"job_id": job_id, "state": j["state"],
                    "progress": dict(j["progress"]),
                    "error": j["error"], "result": j["result"]}

    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._queue:
                    self._cond.wait()
                job_id, params = self._queue.pop(0)
                self._jobs[job_id]["state"] = "running"
            cached = _cached(_result_cache, _cache_key(params))
            if cached is not None:
                self._finish(job_id, result=cached)
                continue
            try:
                res = run_test(params,
                               progress=lambda a, b, s,
                               j=job_id: self._progress(j, a, b, s))
            except Exception as e:  # noqa: BLE001 - report to caller
                self._finish(job_id, error=str(e))
            else:
                _put_cached(_result_cache, _cache_key(params), res)
                self._finish(job_id, result=res)

    def _progress(self, job_id: str, loaded: int, total: int,
                  stage: str) -> None:
        with self._cond:
            j = self._jobs.get(job_id)
            if j:
                j["progress"] = {"loaded": loaded, "total": total,
                                 "stage": stage}

    def _finish(self, job_id: str, result: dict | None = None,
                error: str | None = None) -> None:
        with self._cond:
            j = self._jobs[job_id]
            j["state"] = "failed" if error else "done"
            j["result"] = result
            j["error"] = error


def _norm_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "factor": params.get("factor", "mom_20"),
        "composite": params.get("composite"),
        "universe": params.get("universe", "top_cap"),
        "universe_size": int(params.get("universe_size", 100)),
        "symbols": ([str(s) for s in params["symbols"]]
                    if params.get("symbols") else None),
        "start_date": params.get("start_date") or "",
        "end_date": params.get("end_date") or "",
        "freq": str(params.get("freq", "M")).upper(),
        "quantiles": int(params.get("quantiles", 5)),
    }


def _cache_key(params: dict[str, Any]) -> str:
    import json
    return json.dumps(params, sort_keys=True, default=str)


jobs = FactorJobs()
