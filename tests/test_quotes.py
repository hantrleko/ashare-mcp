"""Offline tests for get_quotes batching (akshare provider stubbed)."""
import pandas as pd

import ashare_mcp.data.akshare_data as ad


def test_get_quotes_small_batch_parallel(monkeypatch):
    """<=20 symbols route through get_quote concurrently, not the snapshot."""
    calls = []
    monkeypatch.setattr(ad, "get_quote",
                        lambda s: calls.append(s) or {"code": s, "price": 1.0})
    monkeypatch.setattr(ad, "_spot_df",
                        lambda: (_ for _ in ()).throw(AssertionError("snapshot")))
    out = ad.get_quotes(["600519", "000001", "300750"])
    assert [r["code"] for r in out] == ["600519", "000001", "300750"]
    assert sorted(calls) == ["000001", "300750", "600519"]


def test_intraday_prev_close_uses_prior_session(monkeypatch):
    """prev_close must be the close of the day BEFORE the intraday session,
    not the session's own close (the old bug made sparklines grey)."""
    minute = pd.DataFrame({
        "day": ["2025-06-10 14:59:00", "2025-06-10 15:00:00"],
        "open": [1480.0, 1484.0], "close": [1484.0, 1485.75],
        "high": [1485.0, 1486.0], "low": [1479.0, 1483.0],
        "volume": [10.0, 12.0],
    })
    monkeypatch.setattr(ad.ak, "stock_zh_a_hist_min_sina",
                        lambda symbol, period: minute)
    # store/network daily bars end AT the session date — last bar is the
    # session's own close and must not be picked as prev_close
    monkeypatch.setattr(ad, "get_kline", lambda *a, **k: [
        {"date": "2025-06-06", "close": 1440.0},
        {"date": "2025-06-09", "close": 1460.21},
        {"date": "2025-06-10", "close": 1485.75},
    ])
    # quote fallback must not win over the daily bar either
    monkeypatch.setattr(ad, "get_quote", lambda s: {
        "code": s, "prev_close": 1485.75, "date": "2025-06-10 15:00:00"})
    r = ad.get_intraday("600519")
    assert r["mode"] == "intraday"
    assert r["prev_close"] == 1460.21
    assert r["points"][-1]["price"] == 1485.75


def test_intraday_prev_close_quote_fallback(monkeypatch):
    """With no earlier daily bar, the quote's prev_close is used only when
    its date matches the session date."""
    minute = pd.DataFrame({
        "day": ["2025-06-10 15:00:00"], "open": [1.0], "close": [11.0],
        "high": [1.0], "low": [1.0], "volume": [1.0],
    })
    monkeypatch.setattr(ad.ak, "stock_zh_a_hist_min_sina",
                        lambda symbol, period: minute)
    monkeypatch.setattr(ad, "get_kline", lambda *a, **k: [
        {"date": "2025-06-10", "close": 11.0}])
    monkeypatch.setattr(ad, "get_quote", lambda s: {
        "code": s, "prev_close": 10.5, "date": "2025-06-10 15:00:00"})
    r = ad.get_intraday("600519")
    assert r["prev_close"] == 10.5
