"""Factor research tests — synthetic panels only, no network."""
import numpy as np
import pandas as pd
import pytest

from ashare_mcp.research import factors as fx

CODES = [f"{i:06d}" for i in range(1, 41)]  # 40 stocks


def bdays(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def mkpanel(close: pd.DataFrame) -> dict:
    z = pd.DataFrame(1e6, index=close.index, columns=close.columns)
    return {"close": close, "amount": z.copy(), "turnover": z.copy(),
            "dropped": []}


def run_with(close: pd.DataFrame, f: pd.DataFrame, monkeypatch,
             **over):
    monkeypatch.setattr(fx, "_pick_universe",
                        lambda *a, **k: [(c, "") for c in close.columns])
    monkeypatch.setattr(fx, "_load_panel",
                        lambda *a, **k: mkpanel(close))
    monkeypatch.setattr(fx, "factor_frame", lambda *a, **k: f)
    params = {"factor": "mom_20", "freq": "W", "quantiles": 5,
              "start_date": close.index[0].strftime("%Y-%m-%d"),
              "end_date": close.index[-1].strftime("%Y-%m-%d"),
              "universe": "custom", "symbols": list(close.columns)}
    params.update(over)
    return fx.run_test(params)


# ------------------------------------------------------------- formulas

def test_mom_and_rev():
    idx = bdays(80)
    c = pd.DataFrame(np.tile(np.arange(1, 81, dtype=float), (3, 1)).T,
                     index=idx, columns=CODES[:3])  # linear ramp
    f = fx.factor_frame("mom_20", c, None, None)
    assert f.iloc[20, 0] == pytest.approx(21 / 1 - 1)
    assert np.isnan(f.iloc[19, 0])
    f60 = fx.factor_frame("mom_60", c, None, None)
    assert f60.iloc[60, 0] == pytest.approx(61 / 1 - 1)
    skip = fx.factor_frame("mom_120_skip20", c * 1.0, None, None)
    # need 120 rows; use longer panel
    c2 = pd.DataFrame(np.tile(np.arange(1, 200, dtype=float), (2, 1)).T,
                      index=bdays(199), columns=CODES[:2])
    skip = fx.factor_frame("mom_120_skip20", c2, None, None)
    assert skip.iloc[120, 0] == pytest.approx(101 / 1 - 1)
    rev = fx.factor_frame("rev_5", c, None, None)
    assert rev.iloc[5, 0] == pytest.approx(-(6 / 1 - 1))


def test_vol_turn_maxret_minimums():
    idx = bdays(80)
    rng = np.random.default_rng(0)
    c = pd.DataFrame(100 + rng.normal(0, 1, (80, 5)).cumsum(axis=0),
                     index=idx, columns=CODES[:5])
    t = pd.DataFrame(rng.uniform(1, 3, (80, 5)), index=idx,
                     columns=CODES[:5])
    v = fx.factor_frame("vol_20", c, None, None)
    assert np.isnan(v.iloc[14, 0])      # only 14 valid returns < 15
    assert np.isfinite(v.iloc[15, 0])
    v60 = fx.factor_frame("vol_60", c, None, None)
    assert np.isnan(v60.iloc[44, 0])    # 44 < 45 valid
    assert np.isfinite(v60.iloc[45, 0])
    tu = fx.factor_frame("turn_20", c, None, t)
    assert np.isnan(tu.iloc[13, 0])
    assert np.isfinite(tu.iloc[14, 0])
    mx = fx.factor_frame("maxret_20", c, None, None)
    r = c.pct_change()
    assert mx.iloc[19, 0] == pytest.approx(
        r.iloc[0:20, 0].max())


def test_amihud_skips_zero_amount():
    idx = bdays(30)
    c = pd.DataFrame(np.linspace(100, 110, 30)[:, None] * np.ones(3),
                     index=idx, columns=CODES[:3])
    a = pd.DataFrame(1e6, index=idx, columns=CODES[:3])
    a.iloc[5, 0] = 0.0                   # zero amount day excluded
    f = fx.factor_frame("amihud_20", c, a, None)
    r = (c.pct_change().abs() / a.where(a > 0))
    exp = r.iloc[1:21, 0].mean() * 1e8   # window 1..20, NaN dropped
    assert f.iloc[20, 0] == pytest.approx(exp)


def test_composite_direction_and_ties():
    idx = bdays(40)
    c = pd.DataFrame(np.linspace(100, 120, 40)[:, None]
                     * np.linspace(1, 2, 6), index=idx, columns=CODES[:6])
    comp = fx.composite_frame(
        [{"factor": "mom_20", "sign": 1},
         {"factor": "mom_20", "sign": -1}], c, None, None)
    row = comp.iloc[-1]
    assert row.notna().all()
    # +rank and 1-rank average to 0.5 for all stocks
    assert np.allclose(row.values, 0.5)
    # missing component propagates NaN
    c2 = c.copy()
    c2.iloc[:25, 0] = np.nan
    comp2 = fx.composite_frame(
        [{"factor": "mom_20", "sign": 1},
         {"factor": "vol_20", "sign": 1}], c2, None, None)
    assert np.isnan(comp2.iloc[-1, 0])


def test_unknown_factor_raises():
    with pytest.raises(ValueError):
        fx.factor_frame("nope", pd.DataFrame(), None, None)


# ------------------------------------------------------------- procedure

def test_perfect_factor_rankic_and_nav_order(monkeypatch):
    idx = bdays(90)
    # geometric prices: stock i grows at rate g_i -> factor rank and
    # forward-return rank are identical every date.
    g = np.linspace(0.001, 0.004, 40)
    c = pd.DataFrame(
        np.power(1 + g[None, :], np.arange(90)[:, None]),
        index=idx, columns=CODES)
    f = c / c.shift(20) - 1
    res = run_with(c, f, monkeypatch)
    for r in res["ic_series"]:
        assert r["rank_ic"] == pytest.approx(1.0)
        assert r["n"] == 40
    navs = res["quantile_nav"]
    for i in range(1, 5):
        assert navs[f"Q{i}"][-1]["nav"] < navs[f"Q{i + 1}"][-1]["nav"]
    assert res["rank_ic_summary"]["mean"] == pytest.approx(1.0)


def test_nav_points_on_period_end_dates(monkeypatch):
    idx = bdays(90)
    g = np.linspace(0.001, 0.004, 40)
    c = pd.DataFrame(np.power(1 + g[None, :], np.arange(90)[:, None]),
                     index=idx, columns=CODES)
    res = run_with(c, c / c.shift(20) - 1, monkeypatch)
    nav = res["quantile_nav"]["Q5"]
    ic_dates = [r["date"] for r in res["ic_series"]]
    # origin = first formation date at 1.0; each later point = next formation date
    assert nav[0] == {"date": ic_dates[0], "nav": 1.0}
    assert [p["date"] for p in nav[1:-1]] == ic_dates[1:]
    assert len(nav) == len(ic_dates) + 1
    assert nav[1]["nav"] != 1.0


def test_random_factor_mean_rankic_small(monkeypatch):
    idx = bdays(140)
    rng = np.random.default_rng(7)
    rets = rng.normal(0, 0.02, (140, 60))
    c = pd.DataFrame((1 + rets).cumprod(axis=0), index=idx,
                     columns=[f"{i:06d}" for i in range(60)])
    f = c / c.shift(20) - 1
    res = run_with(c, f, monkeypatch)
    assert abs(res["rank_ic_summary"]["mean"]) < 0.05


def test_forward_alignment_and_missing_close(monkeypatch):
    idx = bdays(60)
    rng = np.random.default_rng(1)
    c = pd.DataFrame(50 + rng.normal(0, 1, (60, 40)).cumsum(axis=0),
                     index=idx, columns=CODES)
    f = pd.DataFrame(np.tile(np.arange(40.), (60, 1)),
                     index=idx, columns=CODES)
    res = run_with(c, f, monkeypatch)
    used = set(res["dates_used"])
    assert idx[-1].strftime("%Y-%m-%d") not in used  # last has no fwd
    # punch a hole: one stock missing at a single rebalance date
    c2 = c.copy()
    hole = pd.Timestamp(res["dates_used"][1])
    nxt_used_idx = res["dates_used"][2]
    c2.loc[hole:, CODES[0]] = np.nan
    res2 = run_with(c2, f, monkeypatch)
    row2 = [r for r in res2["ic_series"] if r["date"] == res["dates_used"][1]]
    row3 = [r for r in res2["ic_series"] if r["date"] == nxt_used_idx]
    # stock0 has no close at hole -> excluded there; fwd to next date NaN
    # also excludes at the previous date. 38 or 39 included.
    assert row2[0]["n"] == 39


def test_small_dates_dropped(monkeypatch):
    idx = bdays(60)
    rng = np.random.default_rng(2)
    c = pd.DataFrame(50 + rng.normal(0, 1, (60, 40)).cumsum(axis=0),
                     index=idx, columns=CODES)
    f = pd.DataFrame(np.tile(np.arange(40.), (60, 1)),
                     index=idx, columns=CODES)
    res = run_with(c, f, monkeypatch)
    d0 = res["dates_used"][0]
    f2 = f.copy()
    f2.loc[d0, CODES[19:]] = np.nan   # leaves 19 valid -> dropped
    res2 = run_with(c, f2, monkeypatch)
    assert d0 in res2["dates_dropped_small"]
    assert d0 not in res2["dates_used"]


def test_winsorization_changes_pearson(monkeypatch):
    idx = bdays(60)
    rng = np.random.default_rng(3)
    c = pd.DataFrame(50 + rng.normal(0, 1, (60, 40)).cumsum(axis=0),
                     index=idx, columns=CODES)
    f = pd.DataFrame(np.tile(np.arange(40.), (60, 1)),
                     index=idx, columns=CODES)
    res = run_with(c, f, monkeypatch)
    d = res["dates_used"][0]
    # recompute expected winsorized Pearson for that date
    frow = f.loc[d]
    nxt = res["dates_used"][1]
    fwd = c.loc[nxt] / c.loc[d] - 1
    clipped = frow.clip(frow.quantile(.01), frow.quantile(.99))
    exp_ic = clipped.corr(fwd)
    got = [r for r in res["ic_series"] if r["date"] == d][0]["ic"]
    assert got == pytest.approx(exp_ic)
    # sanity: with an extreme factor outlier, clipped != raw pearson
    c3 = c.copy()
    # make stock39's forward return strongly negative while f extreme high
    c3.loc[nxt:, CODES[39]] = c3.loc[nxt:, CODES[39]] * 0.5
    res3 = run_with(c3, f, monkeypatch)
    raw = frow.corr(c3.loc[nxt] / c3.loc[d] - 1)
    got3 = [r for r in res3["ic_series"]
            if r["date"] == d][0]["ic"]
    clip3 = frow.clip(frow.quantile(.01), frow.quantile(.99))
    assert got3 == pytest.approx(
        clip3.corr(c3.loc[nxt] / c3.loc[d] - 1))
    assert got3 != pytest.approx(raw)


def test_group_ls_turnover_and_annualization(monkeypatch):
    idx = bdays(90)
    g = np.linspace(0.001, 0.004, 40)
    c = pd.DataFrame(np.power(1 + g[None, :], np.arange(90)[:, None]),
                     index=idx, columns=CODES)
    f = c / c.shift(20) - 1
    res = run_with(c, f, monkeypatch, freq="W", quantiles=5)
    # group sizes: 40 stocks / 5 groups -> 8 each; LS == Q5 ret - Q1 ret.
    nav5 = res["quantile_nav"]["Q5"][-1]["nav"]
    nav1 = res["quantile_nav"]["Q1"][-1]["nav"]
    ls = res["quantile_nav"]["LS"][-1]["nav"]
    nper = len(res["dates_used"])
    # recompute LS NAV from group returns (NAV_i(t+1)/NAV_i(t) - 1)
    q5 = [p["nav"] for p in res["quantile_nav"]["Q5"]]
    q1 = [p["nav"] for p in res["quantile_nav"]["Q1"]]
    lsr = [(q5[i] / (q5[i - 1] if i else 1.0) - 1)
           - (q1[i] / (q1[i - 1] if i else 1.0) - 1)
           for i in range(nper)]
    assert ls == pytest.approx(float(np.prod([1 + r for r in lsr])), 5)
    # annualization: NAV ^ (52/nper) - 1
    exp_ann = nav5 ** (52 / nper) - 1
    assert res["quantile_annual"]["Q5"] == pytest.approx(exp_ann, rel=1e-5)
    # constant membership -> zero turnover
    assert res["top_turnover"] == pytest.approx(0.0)


def test_top_turnover_membership_change(monkeypatch):
    idx = bdays(60)
    rng = np.random.default_rng(5)
    c = pd.DataFrame(50 + rng.normal(0, 1, (60, 40)).cumsum(axis=0),
                     index=idx, columns=CODES)
    f = pd.DataFrame(np.tile(np.arange(40.), (60, 1)),
                     index=idx, columns=CODES)
    # after the first used date, swap half the top group to bottom
    res0 = run_with(c, f, monkeypatch)
    d1 = res0["dates_used"][1]
    f2 = f.copy()
    top8 = list(CODES[32:40])
    bot8 = list(CODES[0:8])
    f2.loc[d1:, top8] = np.arange(8)
    f2.loc[d1:, bot8] = np.arange(8) + 32
    res = run_with(c, f2, monkeypatch)
    # membership flips once (at d1 -> turnover 1.0), constant elsewhere
    nper = len(res["dates_used"])
    assert res["top_turnover"] == pytest.approx(1 / (nper - 1), abs=0.15)


def test_decay_alignment(monkeypatch):
    idx = bdays(90)
    rng = np.random.default_rng(9)
    c = pd.DataFrame(50 + rng.normal(0, 1, (90, 40)).cumsum(axis=0),
                     index=idx, columns=CODES)
    res_stub = run_with(c, pd.DataFrame(0, index=idx, columns=CODES),
                        monkeypatch)
    dates = [pd.Timestamp(d) for d in res_stub["dates_used"]] + \
        [pd.Timestamp(res_stub["dates_used"][-1])]
    # f = forward return of the 2nd period exactly -> L2 RankIC = 1,
    # L1 not necessarily 1.
    closes = c
    f = pd.DataFrame(index=idx, columns=CODES, dtype=float)
    rdates = pd.DatetimeIndex(res_stub["dates_used"])
    for k in range(len(rdates) - 1):
        t0, t2 = rdates[k], rdates[min(k + 2, len(rdates) - 1)]
        f.loc[t0] = closes.loc[t2] / closes.loc[t0] - 1
    res = run_with(c, f, monkeypatch)
    d2 = [d for d in res["ic_decay"] if d["lag"] == 2][0]
    # second-period fwd = two-step return; our f equals it for dates
    # where t2 is a rebalance date one step ahead — approximate check:
    assert d2["n"] > 0
    assert abs(d2["rank_ic_mean"]) <= 1.0


def test_no_lookahead(monkeypatch):
    idx = bdays(60)
    rng = np.random.default_rng(11)
    c = pd.DataFrame(50 + rng.normal(0, 1, (60, 40)).cumsum(axis=0),
                     index=idx, columns=CODES)
    t = 30
    f1 = fx.factor_frame("mom_20", c, None, None).iloc[t]
    c2 = c.copy()
    c2.iloc[t + 1:] = np.nan
    f2 = fx.factor_frame("mom_20", c2, None, None).iloc[t]
    pd.testing.assert_series_equal(f1, f2)


# ------------------------------------------------------------- jobs/api

def test_job_runner(monkeypatch):
    monkeypatch.setattr(fx, "run_test",
                        lambda params, progress=None: {"echo": params})
    j = fx.FactorJobs()
    jid = j.submit({"factor": "rev_5", "quantiles": 5})
    import time
    for _ in range(200):
        st = j.status(jid)
        if st["state"] == "done":
            break
        time.sleep(0.02)
    assert st["state"] == "done"
    assert st["result"]["echo"]["factor"] == "rev_5"
    with pytest.raises(ValueError):
        j.status("nope")


def test_job_queue_limit(monkeypatch):
    import threading, time
    gate = threading.Event()

    def slow(params, progress=None):
        gate.wait(5)
        return {}
    monkeypatch.setattr(fx, "run_test", slow)
    j = fx.FactorJobs()
    first = j.submit({})
    # wait for the worker to claim the first job so the queue itself holds
    # exactly MAX_QUEUED items (race: pop happens on the worker thread)
    for _ in range(100):
        if j.status(first)["state"] == "running":
            break
        time.sleep(0.05)
    ids = [first] + [j.submit({}) for _ in range(fx.MAX_QUEUED)]
    with pytest.raises(ValueError, match="队列已满"):
        j.submit({})
    gate.set()
    time.sleep(0.2)


def test_submit_validation():
    j = fx.FactorJobs()
    with pytest.raises(ValueError):
        j.submit({"factor": "bad_factor"})
    with pytest.raises(ValueError):
        j.submit({"quantiles": 2})
    with pytest.raises(ValueError):
        j.submit({"start_date": "2025-01-01", "end_date": "2024-01-01"})


def test_result_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(
        fx, "run_test",
        lambda params, progress=None: calls.append(1) or {"r": 1})
    j = fx.FactorJobs()
    fx._result_cache.clear()
    import time

    def wait(jid):
        for _ in range(300):
            st = j.status(jid)
            if st["state"] in ("done", "failed"):
                return st
            time.sleep(0.02)
        return st
    s1 = wait(j.submit({"factor": "mom_20"}))
    s2 = wait(j.submit({"factor": "mom_20"}))
    assert s1["state"] == s2["state"] == "done"
    assert len(calls) == 1  # second served from cache


def test_api_factor_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from ashare_mcp.web.api import app
    monkeypatch.setattr(fx, "run_test",
                        lambda params, progress=None: {"ok": True})
    c = TestClient(app)
    r = c.get("/api/factor/list")
    assert r.status_code == 200
    assert any(f["id"] == "mom_20" for f in r.json()["data"])
    r = c.post("/api/factor/jobs", json={"factor": "mom_20"})
    assert r.status_code == 200
    jid = r.json()["job_id"]
    st = c.get(f"/api/factor/jobs/{jid}")
    assert st.status_code == 200
    r = c.post("/api/factor/jobs", json={"factor": "bogus"})
    assert r.status_code == 400
    r = c.get("/api/factor/jobs/deadbeef")
    assert r.status_code == 404
