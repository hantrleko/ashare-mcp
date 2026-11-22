"""Industry peers + valuation percentile tests (spot snapshot stubbed)."""
import math

import pandas as pd
import pytest

import ashare_mcp.data.akshare_data as ad
from ashare_mcp.research import peers as P
from ashare_mcp.research.industry import industry_map


def _spot():
    return pd.DataFrame([
        # industry A: 5 stocks
        dict(code6="600001", name="A1", price=10, pct_chg=1, pe_ttm=10,
             pb=1.0, mkt_cap=100e8, turnover=2),
        dict(code6="600002", name="A2", price=20, pct_chg=-1, pe_ttm=20,
             pb=2.0, mkt_cap=50e8, turnover=1),
        dict(code6="600003", name="A3", price=30, pct_chg=0, pe_ttm=20,
             pb=4.0, mkt_cap=30e8, turnover=3),   # tie PE with A2
        dict(code6="600004", name="A4", price=40, pct_chg=2, pe_ttm=-5,
             pb=float("nan"), mkt_cap=20e8, turnover=4),  # invalid PE/PB
        dict(code6="600005", name="A5", price=50, pct_chg=3, pe_ttm=None,
             pb=1.5, mkt_cap=10e8, turnover=0.5),         # missing PE
        # industry B
        dict(code6="600006", name="B1", price=5, pct_chg=0, pe_ttm=8,
             pb=0.8, mkt_cap=5e8, turnover=1),
    ])


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    monkeypatch.setattr(ad, "_spot_df", _spot)
    monkeypatch.setattr(P, "industry_map", lambda: {
        "600001": "银行", "600002": "银行", "600003": "银行",
        "600004": "银行", "600005": "银行", "600006": "地产"})


def test_pctile_math_ties():
    # below + half-ties over n
    assert P._pctile([10, 20, 20, 30], 20) == pytest.approx(
        100 * (1 + 1) / 4)          # 1 below, 2 ties -> 50
    assert P._pctile([10, 20, 30], 5) == pytest.approx(0.0)
    assert P._pctile([10, 20, 30], 30) == pytest.approx(83.3)


def test_pctile_invalid():
    assert P._pctile([10, 20], None) is None
    assert P._pctile([10, 20], -5) is None
    assert P._pctile([10, 20], float("nan")) is None
    # non-positive samples are excluded -> empty sample -> None
    assert P._pctile([-1, 0], 10) is None
    # non-positive sample values dropped: x=1 vs {5} -> (0+0.5)/1 = 50
    assert P._pctile([-1, 0, 5], 1) == pytest.approx(0.0)


def test_peers_basic():
    r = P.industry_peers("600001")
    assert r["industry"] == "银行"
    assert r["count"] == 5
    assert r["stock"]["is_me"] is True
    assert r["stock"]["code"] == "600001"
    # top-4 by mkt_cap within limit=4
    r4 = P.industry_peers("600001", limit=4)
    assert len(r4["peers"]) == 4
    assert r4["peers"][0]["code"] == "600001"
    # percentiles of A1 (pe=10 vs valid {10,20,20}): (0 + 0.5)/3 -> 16.7
    assert r["stock"]["percentiles"]["pe_ttm"] == pytest.approx(16.7)
    # mkt_cap 100e8 largest of 5 -> (4 + 0.5)/5 = 90
    assert r["stock"]["percentiles"]["mkt_cap"] == pytest.approx(90.0)
    # roe_est: A1 pb/pe*100 = 10 -> peers values valid positives
    med = r["medians"]["pe_ttm"]
    assert med == pytest.approx(20)   # median of {10,20,20}


def test_stock_invalid_pe_null_percentile():
    r = P.industry_peers("600004")   # pe=-5 invalid
    assert r["stock"]["percentiles"]["pe_ttm"] is None
    assert r["stock"]["percentiles"]["pb"] is None      # nan
    assert r["stock"]["percentiles"]["mkt_cap"] is not None


def test_unknown_symbol():
    with pytest.raises(ValueError):
        P.industry_peers("999999")


def test_limit_includes_stock_flag():
    r = P.industry_peers("600006", limit=30)
    assert r["industry"] == "地产"
    assert r["count"] == 1
    assert len(r["peers"]) == 1 and r["peers"][0]["is_me"]
    # single-member industry: percentile = 0.5/1 = 50
    assert r["stock"]["percentiles"]["pe_ttm"] == pytest.approx(50.0)
