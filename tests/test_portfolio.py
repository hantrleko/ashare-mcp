"""Offline tests for the portfolio backtest — klines stubbed."""
import pandas as pd
import pytest

import ashare_mcp.backtest.portfolio as pf


def _bars(dates, price):
    return [{"date": str(d.date()), "open": p, "high": p * 1.01,
             "low": p * 0.99, "close": p, "volume": 1e6, "amount": 1e7}
            for d, p in zip(dates, price)]


def _feed(series_by_code, bench_close):
    """series_by_code: {code6: {pd.Timestamp: price}}; missing dates = no bar."""
    def call(name, *args, **kwargs):
        if name == "get_kline":
            sym = args[0][-6:]
            bars = _bars(sorted(series_by_code[sym]),
                         [series_by_code[sym][d]
                          for d in sorted(series_by_code[sym])])
            return bars, "test"
        if name == "get_index_kline":
            dates = sorted(bench_close)
            return _bars(dates, [bench_close[d] for d in dates]), "test"
        raise RuntimeError(name)
    return call


CAL = list(pd.bdate_range("2024-01-01", periods=90))


@pytest.fixture
def feed(monkeypatch):
    """Default: two flat-priced symbols, flat benchmark."""
    data = {
        "600001": {d: 10.0 for d in CAL},
        "000002": {d: 20.0 for d in CAL},
    }
    bench = {d: 100.0 for d in CAL}
    monkeypatch.setattr(pf.market_data, "call", _feed(data, bench))
    monkeypatch.setattr(pf, "_name_of", lambda c: c)
    monkeypatch.setattr(pf, "_limit_of", lambda c: 0.10)
    return data


def test_equal_weight_first_rebalance(feed):
    r = pf.run_portfolio_backtest(["600001", "000002"], "equal", "M",
                                  "20240101", "20240430", 100_000.0)
    assert r["num_rebalances"] >= 1
    # same capital weight: shares_600001*10 == shares_000002*20
    h = {x["code"]: x for x in r["final_holdings"]}
    assert h["600001"]["shares"] * 10 == pytest.approx(
        h["000002"]["shares"] * 20, rel=0.05)


def test_monthly_rebalance_dates(feed):
    r = pf.run_portfolio_backtest(["600001", "000002"], "equal", "M",
                                  "20240101", "20240430", 100_000.0)
    months = {x["date"][:7] for x in r["rebalance_log"]}
    assert months == {str(d)[:7] for d in CAL}
    for x in r["rebalance_log"]:
        d = pd.Timestamp(x["date"])
        prev = [c for c in CAL if c < d and c.month == d.month]
        assert not prev  # first trading day of the month


def test_suspended_symbol_skipped_and_valued(monkeypatch):
    data = {
        "600001": {d: 10.0 for d in CAL},
        # 000002 stops trading after day 30
        "000002": {d: 20.0 for d in CAL[:30]},
    }
    bench = {d: 100.0 for d in CAL}
    monkeypatch.setattr(pf.market_data, "call", _feed(data, bench))
    monkeypatch.setattr(pf, "_name_of", lambda c: c)
    monkeypatch.setattr(pf, "_limit_of", lambda c: 0.10)
    r = pf.run_portfolio_backtest(["600001", "000002"], "equal", "M",
                                  "20240101", "20240430", 100_000.0)
    # no orders for 000002 after its last bar date (2024-02-13 = CAL[29]);
    # its position is kept and valued at the last close
    last_bar = str(CAL[29].date())
    late = [t for t in r.get("trades", [])
            if t.get("symbol") == "000002" and t["date"] > last_bar]
    assert not late
    h = {x["code"]: x for x in r["final_holdings"]}
    assert "600001" in h and h["000002"]["shares"] > 0


def test_late_listing_joins_next_rebalance(monkeypatch):
    data = {
        "600001": {d: 10.0 for d in CAL},
        "000002": {d: 20.0 for d in CAL[45:]},   # lists mid-March
    }
    bench = {d: 100.0 for d in CAL}
    monkeypatch.setattr(pf.market_data, "call", _feed(data, bench))
    monkeypatch.setattr(pf, "_name_of", lambda c: c)
    monkeypatch.setattr(pf, "_limit_of", lambda c: 0.10)
    r = pf.run_portfolio_backtest(["600001", "000002"], "equal", "M",
                                  "20240101", "20240430", 100_000.0)
    buys = [t for t in r.get("trades", [])
            if t.get("symbol") == "000002" and t["side"] == "buy"]
    assert buys and buys[0]["date"] >= "2024-04-01"


def test_limit_up_open_blocks_buy(monkeypatch):
    # 000002 lists on Jan 31 (close 10); at the Feb-1 rebalance its open
    # is 11.0 = prev*(1+10%) -> the fresh buy is blocked at the limit-up open
    data = {
        "600001": {d: 10.0 for d in CAL},
        "000002": {d: (10.0 if i == 22 else 11.0)
                   for i, d in enumerate(CAL) if i >= 22},
    }
    bench = {d: 100.0 for d in CAL}
    monkeypatch.setattr(pf.market_data, "call", _feed(data, bench))
    monkeypatch.setattr(pf, "_name_of", lambda c: c)
    monkeypatch.setattr(pf, "_limit_of", lambda c: 0.10)
    r = pf.run_portfolio_backtest(["600001", "000002"], "equal", "M",
                                  "20240101", "20240430", 100_000.0)
    assert r["blocked_orders"] >= 1


def test_inverse_vol_prefers_low_vol(monkeypatch):
    import numpy as np
    rng = np.random.default_rng(7)
    data = {
        "600001": {d: 10.0 for d in CAL},                          # zero vol
        "000002": {d: 20.0 * (1 + 0.02 * np.sin(i)) for i, d in enumerate(CAL)},
    }
    bench = {d: 100.0 for d in CAL}
    monkeypatch.setattr(pf.market_data, "call", _feed(data, bench))
    monkeypatch.setattr(pf, "_name_of", lambda c: c)
    monkeypatch.setattr(pf, "_limit_of", lambda c: 0.10)
    r = pf.run_portfolio_backtest(["600001", "000002"], "inverse_vol", "M",
                                  "20240101", "20240430", 100_000.0)
    h = {x["code"]: x for x in r["final_holdings"]}
    assert h["600001"]["value"] > h["000002"]["value"]


def test_benchmark_normalized(feed):
    r = pf.run_portfolio_backtest(["600001", "000002"], "equal", "M",
                                  "20240101", "20240430", 100_000.0)
    assert r["equity_curve"][0]["benchmark"] == pytest.approx(100_000.0,
                                                            rel=0.01)
    assert "benchmark_total_return" in r and "excess_annual" in r
    assert r["annual_turnover"] is not None


def test_symbol_count_bounds(feed):
    with pytest.raises(ValueError):
        pf.run_portfolio_backtest(["600001"], "equal", "M")
    with pytest.raises(ValueError):
        pf.run_portfolio_backtest([f"60{i:04d}" for i in range(51)],
                                  "equal", "M")


def test_skipped_symbols(monkeypatch):
    data = {
        "600001": {d: 10.0 for d in CAL},
        "000002": {d: 20.0 for d in CAL},
        "000003": {},   # no data
    }
    bench = {d: 100.0 for d in CAL}
    monkeypatch.setattr(pf.market_data, "call", _feed(data, bench))
    monkeypatch.setattr(pf, "_name_of", lambda c: c)
    monkeypatch.setattr(pf, "_limit_of", lambda c: 0.10)
    r = pf.run_portfolio_backtest(["600001", "000002", "000003"],
                                  "equal", "M", "20240101", "20240430")
    assert r["skipped_symbols"] == ["000003"]
    # only one valid symbol left -> error
    with pytest.raises(ValueError):
        pf.run_portfolio_backtest(["600001", "000003", "000003"],
                                  "equal", "M", "20240101", "20240430")
