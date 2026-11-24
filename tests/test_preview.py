"""Arena preview: look-ahead-free weekly NAV for price-only house rules."""
from __future__ import annotations

import pytest

from ashare_mcp.trading import house


def _biz_dates(n: int) -> list[str]:
    """n consecutive weekday dates ending 2026-11-20 (a Friday)."""
    from datetime import date, timedelta
    out, d = [], date(2026, 11, 20)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


DATES = _biz_dates(200)
REBS = house._weekly_rebalance_dates(DATES[-120:])


def _mk_kline(closes: dict[str, list[float]]):
    """closes[code] aligned with DATES."""
    def gk(code, **kw):
        return ([{"date": d, "close": c}
                 for d, c in zip(DATES, closes[code])], None)
    return gk


def _mk_index():
    return lambda s, **kw: ([{"date": d, "close": 1000 * (1.001 ** i)}
                             for i, d in enumerate(DATES)], None)


def _universe_closes(n_steady: int = 12):
    """n_steady uptrend stocks + one 'late' stock that only spikes after
    the second-to-last rebalance date."""
    closes = {}
    for i in range(n_steady):
        closes[f"S{i:02d}"] = [100 * (1.004 ** j) for j in range(len(DATES))]
    # spikes strictly between the last two computed rebalances so it is
    # invisible at REBS[-3] but visible at the latest rebalance REBS[-2]
    spike_at = DATES.index(REBS[-3]) + 1
    late = [100.0] * len(DATES)
    for j in range(spike_at, len(DATES)):
        late[j] = late[j - 1] * 1.5
    closes["LATE"] = late
    return closes, spike_at


def test_no_lookahead():
    closes, _ = _universe_closes()
    uni = list(closes)
    res = house.preview_backtest(
        universe=uni, names={c: c for c in uni},
        get_kline=_mk_kline(closes), get_index_kline=_mk_index(),
        window_days=120)
    # at the last computed rebalance the spike is visible -> LATE selected
    last_codes = {t["code"] for t in res["latest"]["momentum"]}
    assert "LATE" in last_codes
    # but truncating at the previous rebalance (before the spike) must not
    t_prev = REBS[-3]
    trunc = {c: house._series_upto(sorted(
        {d: v for d, v in zip(DATES, closes[c])}.items()), t_prev)
        for c in uni}
    prev_codes = {t["code"] for t in
                  house._momentum_targets(trunc, {c: c for c in uni})}
    assert "LATE" not in prev_codes


def test_nav_math():
    closes, _ = _universe_closes()
    uni = list(closes)
    res = house.preview_backtest(
        universe=uni, names={c: c for c in uni},
        get_kline=_mk_kline(closes), get_index_kline=_mk_index(),
        window_days=120)
    mom = res["series"]["momentum"]
    dates = res["dates"]
    assert len(mom) == len(dates) and mom[0] == 1.0
    # recompute period k independently: signal at weekly reb date rebs_sig[k],
    # entered at dates[k] (next trading day close), held to dates[k+1]
    rebs_sig = [d for d in house._weekly_rebalance_dates(DATES)
                if d in set(DATES[-120:])]
    k = 3
    t = rebs_sig[k]
    trunc = {c: house._series_upto(
        sorted({d: v for d, v in zip(DATES, closes[c])}.items()), t)
        for c in uni}
    tgts = house._momentum_targets(trunc, {c: c for c in uni})
    rets = []
    for tg in tgts:
        pairs = sorted({d: v for d, v in
                        zip(DATES, closes[tg["code"]])}.items())
        rets.append(house._close_le(pairs, dates[k + 1])
                    / house._close_le(pairs, dates[k]) - 1)
    expected = mom[k] * (1 + sum(rets) / len(rets))
    assert mom[k + 1] == pytest.approx(expected, abs=1e-4)


def test_signal_day_jump_not_captured():
    """A jump at the ENTRY-day close (day after the signal) must not be
    captured: entry is that close, not the signal-day close."""
    closes = {f"S{i:02d}": [100 * (1.004 ** j) for j in range(len(DATES))]
              for i in range(12)}
    rebs_sig = [d for d in house._weekly_rebalance_dates(DATES)
                if d in set(DATES[-120:])]
    k = 5
    t = rebs_sig[k]
    entry_idx = next(i for i, d in enumerate(DATES) if d > t)
    # JUMP: slightly stronger steady growth (top pick), leaps x1.5 at the
    # entry-day close, flat afterwards.
    jump = [100 * (1.005 ** j) for j in range(len(DATES))]
    for j in range(entry_idx, len(DATES)):
        jump[j] = jump[entry_idx - 1] * 1.5
    closes["JUMP"] = jump
    # JUMP2: same steady growth, leaps x1.5 on the day AFTER the entry day
    # (inside the holding window -> that return IS captured).
    jump2 = [100 * (1.006 ** j) for j in range(len(DATES))]
    for j in range(entry_idx + 1, len(DATES)):
        jump2[j] = jump2[entry_idx] * 1.5
    closes["JUMP2"] = jump2
    uni = list(closes)
    res = house.preview_backtest(
        universe=uni, names={c: c for c in uni},
        get_kline=_mk_kline(closes), get_index_kline=_mk_index(),
        window_days=120)
    mom = res["series"]["momentum"]
    dates = res["dates"]
    assert dates[k] == DATES[entry_idx]
    # JUMP selected at signal date t?
    trunc = {c: house._series_upto(
        sorted({d: v for d, v in zip(DATES, closes[c])}.items()), t)
        for c in uni}
    tgts = house._momentum_targets(trunc, {c: c for c in uni})
    assert {"JUMP", "JUMP2"} <= {x["code"] for x in tgts}
    # its period return entry->exit is ~0 (flat after the leap); with
    # same-bar entry at t it would be ~+0.5, lifting the mean by ~0.05.
    rets = []
    for tg in tgts:
        pairs = sorted({d: v for d, v in
                        zip(DATES, closes[tg["code"]])}.items())
        rets.append(house._close_le(pairs, dates[k + 1])
                    / house._close_le(pairs, dates[k]) - 1)
    expected = mom[k] * (1 + sum(rets) / len(rets))
    assert mom[k + 1] == pytest.approx(expected, abs=1e-4)
    # JUMP's own entry->exit return is ~0 (flat after the leap), while a
    # same-bar fill at the signal-day close would have captured ~+50%.
    jpairs = sorted({d: v for d, v in zip(DATES, closes["JUMP"])}.items())
    jret = (house._close_le(jpairs, dates[k + 1])
            / house._close_le(jpairs, dates[k]) - 1)
    assert jret == pytest.approx(0.0, abs=1e-9)
    same_bar = (house._close_le(jpairs, dates[k + 1])
                / house._close_le(jpairs, t) - 1)
    assert same_bar == pytest.approx(0.5, abs=1e-9)
    # a jump inside the holding window (entry close -> exit close) IS
    # captured: JUMP2's period return is ~+50%.
    j2pairs = sorted({d: v for d, v in zip(DATES, closes["JUMP2"])}.items())
    j2ret = (house._close_le(j2pairs, dates[k + 1])
             / house._close_le(j2pairs, dates[k]) - 1)
    assert j2ret == pytest.approx(0.5, abs=1e-2)


def test_benchmark_alignment():
    closes, _ = _universe_closes()
    res = house.preview_backtest(
        universe=list(closes), names={c: c for c in closes},
        get_kline=_mk_kline(closes), get_index_kline=_mk_index(),
        window_days=120)
    rebs = res["dates"]
    bench = res["series"]["bench"]
    iclose = {d: 1000 * (1.001 ** i) for i, d in enumerate(DATES)}
    for k in (1, 5, len(rebs) - 1):
        assert bench[k] == pytest.approx(
            iclose[rebs[k]] / iclose[rebs[0]], abs=1e-4)


def test_stats_and_shape():
    closes, _ = _universe_closes()
    res = house.preview_backtest(
        universe=list(closes), names={c: c for c in closes},
        get_kline=_mk_kline(closes), get_index_kline=_mk_index(),
        window_days=120)
    assert res["stats"]["trend"]["total"] == \
        round(res["series"]["trend"][-1] - 1, 4)
    assert res["stats"]["momentum"]["max_dd"] <= 0
    assert set(res["series"]) == {"trend", "momentum", "bench"}
    assert len(res["latest"]["momentum"]) <= house.TOP_N
    assert "幸存者偏差" in res["caption"]
    assert "低估值" in res["value_note"]
