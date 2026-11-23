"""get_index_quote Tencent fallback for indices missing from the sina
snapshot (e.g. bj899050 北证50)."""
import pandas as pd
import pytest

import ashare_mcp.data.akshare_data as ad


def _sina_snapshot() -> pd.DataFrame:
    return pd.DataFrame({
        "code": ["sh000001", "sz399001"],
        "code6": ["000001", "399001"],
        "name": ["上证指数", "深证成指"],
        "price": [3538.95, 10454.37],
    })


def test_index_quote_bj_falls_back_to_tencent(monkeypatch):
    monkeypatch.setattr(ad, "_index_spot_df", _sina_snapshot)
    tdf = pd.DataFrame({
        "code": ["899050"], "name": ["北证50"],
        "price": [795.38], "pct_chg": [4.67], "change": [35.48],
        "prev_close": [759.90], "open": [762.0],
        "high": [800.0], "low": [758.0],
        "volume": [1e6], "amount": [11298994800.0],
    })
    got = {}

    def fake(syms):
        got["syms"] = list(syms)
        return tdf
    monkeypatch.setattr(ad.tencent, "fetch_quotes", fake)
    q = ad.get_index_quote("bj899050")
    assert got["syms"] == ["bj899050"]
    assert q["code"] == "899050"
    assert q["name"] == "北证50"
    assert q["price"] == pytest.approx(795.38)
    assert q["amount"] == pytest.approx(1.12989948e10)


def test_index_quote_empty_everywhere_raises(monkeypatch):
    monkeypatch.setattr(ad, "_index_spot_df", _sina_snapshot)
    monkeypatch.setattr(ad.tencent, "fetch_quotes",
                        lambda syms: pd.DataFrame())
    with pytest.raises(KeyError):
        ad.get_index_quote("bj899050")


def test_index_quote_sina_hit_does_not_call_tencent(monkeypatch):
    monkeypatch.setattr(ad, "_index_spot_df", _sina_snapshot)

    def boom(syms):
        raise AssertionError("tencent should not be called")
    monkeypatch.setattr(ad.tencent, "fetch_quotes", boom)
    q = ad.get_index_quote("sh000001")
    assert q["name"] == "上证指数"
