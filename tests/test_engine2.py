"""Engine correctness fixes (_simulate) + parameter-scan tests — offline."""
import pandas as pd
import pytest

import ashare_mcp.backtest.engine as engine
from ashare_mcp.backtest.engine import _BUILDERS


def _df_from(closes, opens=None, highs=None, lows=None, start="2024-01-01"):
    n = len(closes)
    opens = opens if opens is not None else closes
    highs = highs if highs is not None else [c * 1.01 for c in closes]
    lows = lows if lows is not None else [c * 0.99 for c in closes]
    return pd.DataFrame({
        "date": pd.bdate_range(start, periods=n),
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": 1e6,
    })


def _synthetic_bars(n: int = 120) -> list[dict]:
    price, recs = 10.0, []
    for i in range(n):
        if i < 40:
            price += 0.06
        elif i < 80:
            price -= 0.08
        else:
            price += 0.10
        recs.append({
            "date": str((pd.Timestamp("2024-01-01")
                         + pd.Timedelta(days=i)).date()),
            "open": price, "high": price * 1.02, "low": price * 0.98,
            "close": price, "volume": 1_000_000, "amount": price * 1e6})
    return recs


@pytest.fixture
def stub_feed(monkeypatch):
    # 200 bars so a 0.7 split leaves >= 60 bars on each side
    monkeypatch.setattr(engine.market_data, "call",
                        lambda *a, **k: (_synthetic_bars(200), "test"))


def test_simulate_marks_after_trade():
    """Equity at day i must include the open_i trade (the old code marked
    BEFORE executing, lagging trades by a day)."""
    df = _df_from([10.0, 10.0, 11.0, 11.0])
    target = pd.Series([0.0, 1.0, 1.0, 1.0])   # signal day0 -> buy open day1
    eq, trades, blocked = engine._simulate(df, target, 100_000.0, 0.0, 0.0,
                                           limit_pct=0.0)
    buy = [t for t in trades if t["side"] == "buy"][0]
    assert buy["date"] == df["date"].iloc[1].strftime("%Y-%m-%d")
    cash = 100_000.0 - buy["amount"] - buy["fee"]
    # equity[1] = post-trade mark at close_1 (not pre-trade cash)
    assert eq.iloc[1] == pytest.approx(cash + buy["shares"] * 10.0, abs=0.01)


def test_simulate_blocks_limit_up_buy():
    # prev close 10, limit 10% -> open 11.0 >= 10*1.1-0.005 -> buy blocked
    df = _df_from([10.0, 11.0, 11.0])
    target = pd.Series([0.0, 1.0, 0.0])
    eq, trades, blocked = engine._simulate(df, target, 100_000.0, 0.0, 0.0,
                                           limit_pct=0.10)
    assert blocked == 1 and not any(t["side"] == "buy" for t in trades)


def test_simulate_blocks_limit_down_sell():
    df = _df_from([10.0, 10.0, 9.0])
    target = pd.Series([0.0, 1.0, 0.0])
    eq, trades, blocked = engine._simulate(df, target, 100_000.0, 0.0, 0.0,
                                           limit_pct=0.10)
    assert blocked == 1
    assert not any(t["side"] == "sell" for t in trades)
    assert any(t["side"] == "buy" for t in trades)


def test_grid_default_bounds_use_calib_window():
    # first 60 bars low=10/high=20; later crash to low=1. With whole-sample
    # bounds (look-ahead) close=5 would map to w~0.6; with calib bounds
    # lo=9.8/hi=20.4 it clips to weight 1.
    closes = [10.0] * 60 + [5.0]
    df = _df_from(closes, lows=[10.0] * 60 + [1.0],
                  highs=[20.0] * 60 + [100.0])
    w = _BUILDERS["grid"](df, {"grids": 10, "calib": 60})
    assert w.iloc[-1] == pytest.approx(1.0)


def test_run_backtest_reports_blocked_and_notes(stub_feed, monkeypatch):
    monkeypatch.setattr(engine, "_name_of", lambda c: "")
    r = engine.run_backtest("000001", "ma_cross", {"fast": 3, "slow": 10},
                            "20240101", "20241231", 1_000_000.0,
                            min_trade_value=0.0)
    assert "blocked_orders" in r and "notes" in r
    r2 = engine.run_backtest("000001", "grid", {"grids": 5},
                             "20240101", "20241231", 1_000_000.0)
    assert any("校准" in n for n in r2["notes"])


# ---------------- parameter scan ----------------

def test_scan_combo_cap_and_bad_params(stub_feed):
    with pytest.raises(ValueError):
        engine.scan_backtest("000001", "ma_cross",
                             {"fast": list(range(1, 12)),
                              "slow": list(range(1, 11))})
    with pytest.raises(ValueError):
        engine.scan_backtest("000001", "ma_cross",
                             {"fast": [5], "bogus": [1]})
    with pytest.raises(ValueError):
        engine.scan_backtest("000001", "buy_hold", {"x": [1]})


def test_scan_skips_fast_ge_slow(stub_feed, monkeypatch):
    monkeypatch.setattr(engine, "_name_of", lambda c: "")
    r = engine.scan_backtest("000001", "ma_cross",
                             {"fast": [5, 30], "slow": [20, 60]},
                             "20240101", "20241231")
    assert [{k: v for k, v in p.items()} for p in r["skipped"]] == [
        {"fast": 30.0, "slow": 20.0}]
    assert r["num_combos"] == 3
    for row in r["results"]:
        assert set(row["is"]) >= {"sharpe", "total_return"}
        assert set(row["oos"]) >= {"sharpe", "total_return"}
    assert 1 <= r["oos_rank_of_best_is"] <= r["num_combos"]
    assert r["axes"]["names"] == ["fast", "slow"]
    assert any("样本外" in n for n in r["notes"])
    # rank consistency: position of best_is params in OOS ordering
    ranked = sorted(r["results"], key=lambda x: x["oos"]["sharpe"],
                    reverse=True)
    assert ranked[r["oos_rank_of_best_is"] - 1]["params"] == \
        r["best_is"]["params"]


def test_scan_split_boundaries(stub_feed, monkeypatch):
    monkeypatch.setattr(engine, "_name_of", lambda c: "")
    r = engine.scan_backtest("000001", "momentum",
                             {"lookback": [10], "threshold": [0.01]},
                             "20240101", "20241231", split=0.7)
    assert r["split_date"]
    with pytest.raises(ValueError):
        engine.scan_backtest("000001", "momentum",
                             {"lookback": [10]}, "20240101", "20241231",
                             split=0.99)
