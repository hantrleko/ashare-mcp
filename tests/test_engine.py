"""Offline tests for the backtest engine — data feed is stubbed."""
import pandas as pd
import pytest

import ashare_mcp.backtest.engine as engine
from ashare_mcp.backtest.engine import _BUILDERS


def _synthetic_bars(n: int = 120) -> list[dict]:
    """Up-down-up price path so MA crosses actually trigger."""
    price, recs = 10.0, []
    for i in range(n):
        if i < 40:
            price += 0.06
        elif i < 80:
            price -= 0.08
        else:
            price += 0.10
        recs.append({
            "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=i),
            "open": price, "high": price * 1.02, "low": price * 0.98,
            "close": price, "volume": 1_000_000, "amount": price * 1e6,
        })
    return [{"date": str(r["date"].date()), **{k: v for k, v in r.items()
             if k != "date"}} for r in recs]


@pytest.fixture
def stub_feed(monkeypatch):
    monkeypatch.setattr(engine.market_data, "call",
                        lambda *a, **k: (_synthetic_bars(), "test"))


def test_run_backtest_metrics(stub_feed):
    r = engine.run_backtest("000001", "ma_cross", {"fast": 3, "slow": 10},
                            "20240101", "20241231", 1_000_000.0,
                            min_trade_value=0.0)
    for k in ("final_equity", "total_return", "annual_return",
              "max_drawdown", "sharpe", "num_trades", "equity_curve",
              "trades"):
        assert k in r
    assert r["num_trades"] >= 2          # at least one buy + one sell
    assert len(r["equity_curve"]) > 0
    assert r["bars"] == 120
    assert r["final_equity"] > 0


def test_buy_hold_never_sells(stub_feed):
    r = engine.run_backtest("000001", "buy_hold", {}, "20240101",
                            "20241231", 1_000_000.0)
    assert r["num_sells"] == 0           # all-in, never exits
    assert r["num_trades"] >= 1


def test_bad_strategy(stub_feed):
    with pytest.raises(ValueError, match="strategy"):
        engine.run_backtest("000001", "nope")


def test_weight_builders():
    df = pd.DataFrame({
        "close": [10, 11, 12, 11, 10, 9, 10, 11, 12, 13],
        "open": 10.0, "high": 13.0, "low": 9.0, "volume": 1e6,
    })
    w = _BUILDERS["ma_cross"](df, {"fast": 2, "slow": 3})
    assert set(w.unique()) <= {0.0, 1.0}
    w = _BUILDERS["momentum"](df, {"lookback": 2, "threshold": 0.01})
    assert w.iloc[-1] == 1.0             # 13 > 12*1.01
    w = _BUILDERS["grid"](df, {"grids": 4, "lower": 9, "upper": 13})
    assert 0.0 <= w.min() and w.max() <= 1.0

def test_monthly_returns(stub_feed):
    r = engine.run_backtest("000001", "buy_hold", {}, "20240101",
                            "20241231", 1_000_000.0)
    mr = r["monthly_returns"]
    assert mr and all("month" in m and "ret" in m for m in mr)
    months = [m["month"] for m in mr]
    assert months == sorted(months) and months[0] == "2024-01"
    assert mr[0]["ret"] > 0


def test_pct_distribution():
    from ashare_mcp.data.akshare_data import _pct_distribution, _DIST_LABELS
    pct = pd.Series([-10, -8, -6, -4, -2, -0.5, 0, 0.5, 2, 4, 6, 8, 10])
    d = _pct_distribution(pct)
    assert [x["range"] for x in d] == _DIST_LABELS
    assert sum(x["count"] for x in d) == len(pct)
    by_label = {x["range"]: x["count"] for x in d}
    assert by_label["0"] == 1 and by_label["≤-9"] == 1 and by_label["≥9"] == 1
