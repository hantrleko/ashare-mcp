"""Regression: store-bypass kline must reindex to _KLINE_COLS — a provider
frame missing ``amplitude``/``change`` returns those keys as None instead
of raising KeyError."""
import pandas as pd
import pytest

from ashare_mcp.data import akshare_data as akd


@pytest.fixture(autouse=True)
def _no_store(monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_STORE", "0")


def _frame():
    # provider frame WITHOUT amplitude / change columns
    return pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03"],
        "code": ["600519", "600519"],
        "open": [1700.0, 1710.0],
        "high": [1720.0, 1725.0],
        "low": [1690.0, 1700.0],
        "close": [1710.0, 1720.0],
        "volume": [1000, 1200],
        "amount": [1.7e6, 2.0e6],
        "turnover": [0.3, 0.4],
    })


def test_get_kline_missing_cols(monkeypatch):
    monkeypatch.setattr(akd, "_kline_daily",
                        lambda *a, **k: (_frame(), "sina"))
    recs = akd.get_kline("600519", start_date="20240101",
                         end_date="20240110")
    assert len(recs) == 2
    assert recs[0]["amplitude"] is None
    assert recs[0]["change"] is None
    assert recs[0]["close"] == pytest.approx(1710.0)


def test_get_index_kline_missing_cols(monkeypatch):
    import akshare as ak
    monkeypatch.setattr(ak, "index_zh_daily_sina",
                        lambda symbol: _frame())
    recs = akd.get_index_kline("sh000300", start_date="20240101",
                               end_date="20240110")
    assert len(recs) == 2
    assert recs[0]["amplitude"] is None
    assert recs[0]["change"] is None
