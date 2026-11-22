"""Offline tests for research.screener / research.industry."""
import json
import time
from datetime import datetime, timedelta

import pandas as pd
import pytest

import ashare_mcp.data.akshare_data as ad
import ashare_mcp.research.industry as ind
import ashare_mcp.research.screener as sc
from ashare_mcp.config import data_dir
from ashare_mcp.data.facade import market_data


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    ind._reset()
    yield
    ind._reset()


def _spot() -> pd.DataFrame:
    return pd.DataFrame([
        # code6, name, price, pct, turn, pe, pb, cap, float_cap, amount, vr, amp
        ("600519", "贵州茅台", 1700.0, 1.2, 0.4, 30.0, 10.0, 2.1e12, 2.1e12, 5e9, 1.1, 2.0),
        ("000001", "平安银行", 12.0, -0.5, 1.0, 5.0, 0.6, 2.3e11, 2.0e11, 1e9, 0.9, 1.0),
        ("300750", "宁德时代", 200.0, 2.5, 1.5, 25.0, 5.0, 8.8e11, 7.0e11, 8e9, 1.3, 3.0),
        ("688981", "中芯国际", 80.0, 0.5, 2.0, 50.0, 3.0, 6.4e11, 1.6e11, 6e9, 1.0, 1.5),
        ("830799", "北交所A", 10.0, 3.0, 4.0, 15.0, 1.5, 2.0e9, 1.5e9, 5e7, 2.0, 5.0),
        ("600666", "ST测试", 5.0, -1.0, 0.2, -3.0, 0.8, 3.0e9, 2.5e9, 2e7, 0.5, 1.0),
        ("000002", "停牌股", float("nan"), 0.0, 0.0, 8.0, 1.0, 1.0e10, 1.0e10, 0.0, 0.0, 0.0),
    ], columns=["code6", "name", "price", "pct_chg", "turnover", "pe_ttm",
                "pb", "mkt_cap", "float_mkt_cap", "amount", "volume_ratio",
                "amplitude"])


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(ad, "_spot_df", _spot)
    # screener binds industry_map at import; patch its own namespace
    monkeypatch.setattr(sc, "industry_map",
                        lambda: {"600519": "白酒行业", "000001": "银行"})


def test_ranges_and_null_bounds(stubbed):
    r = sc.screen(ranges={"pe_ttm": [0, 20], "pb": [None, 2]})
    codes = {x["code"] for x in r["rows"]}
    assert codes == {"000001", "830799"}  # NaN-pe ST also excluded by exclude_st
    assert r["total_universe"] == 7


def test_nan_rows_fail_active_range(stubbed):
    # 停牌股 has NaN price -> fails a price range; ST pe<0 fails pe range
    r = sc.screen(ranges={"price": [1, 2000]}, exclude_st=False,
                  exclude_suspended=False)
    assert "000002" not in {x["code"] for x in r["rows"]}


def test_exclude_st_and_suspended(stubbed):
    r = sc.screen(exclude_st=True, exclude_suspended=True)
    codes = {x["code"] for x in r["rows"]}
    assert "600666" not in codes and "000002" not in codes
    r2 = sc.screen(exclude_st=False, exclude_suspended=False)
    codes2 = {x["code"] for x in r2["rows"]}
    assert "600666" in codes2 and "000002" in codes2


def test_industry_and_board_filters(stubbed):
    r = sc.screen(industries=["白酒行业"])
    assert [x["code"] for x in r["rows"]] == ["600519"]
    assert all(x["industry"] == "白酒行业" for x in r["rows"])
    r = sc.screen(boards=["chinext", "bse"])
    assert {x["code"] for x in r["rows"]} == {"300750", "830799"}
    assert {x["board"] for x in r["rows"]} == {"chinext", "bse"}


def test_roe_est_requires_positive_pe_pb(stubbed):
    r = sc.screen(sort_by="roe_est")
    by_code = {x["code"]: x for x in r["rows"]}
    assert by_code["000001"]["roe_est"] == pytest.approx(0.6 / 5.0 * 100)
    # pe = -3 -> roe_est must be null, not negative
    r2 = sc.screen(exclude_st=False, ranges={"roe_est": [1, None]})
    assert "600666" not in {x["code"] for x in r2["rows"]}


def test_unknown_inputs(stubbed):
    with pytest.raises(ValueError):
        sc.screen(ranges={"nope": [0, 1]})
    with pytest.raises(ValueError):
        sc.screen(boards=["mars"])
    with pytest.raises(ValueError):
        sc.screen(sort_by="nope")


def test_momentum_only_for_candidates(stubbed, monkeypatch):
    calls = []

    def fake_call(name, *a, **k):
        calls.append(a[0])
        closes = [{"close": float(i + 1)} for i in range(70)]
        return closes, "fake"

    monkeypatch.setattr(market_data, "call", fake_call)
    # stage-1 = only bse stock via board filter -> 1 kline call
    r = sc.screen(boards=["bse"], sort_by="mom_20")
    assert calls == ["830799"]
    assert r["rows"][0]["mom_20"] == pytest.approx((70 / 50 - 1) * 100)


def test_momentum_cap(stubbed, monkeypatch):
    big = pd.concat([_spot()] * 60, ignore_index=True)
    big["code6"] = [f"6{i:05d}" for i in range(len(big))]
    monkeypatch.setattr(ad, "_spot_df", lambda: big)
    monkeypatch.setattr(market_data, "call",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("should not reach kline")))
    with pytest.raises(ValueError, match="200"):
        sc.screen(sort_by="mom_20")


def test_momentum_failure_is_nan_and_filtered(stubbed, monkeypatch):
    monkeypatch.setattr(market_data, "call",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    r = sc.screen(boards=["bse"], momentum={"mom_20": [0, None]})
    assert r["rows"] == []  # failed kline -> NaN -> fails active range


def test_sort_limit_and_json_safe(stubbed):
    r = sc.screen(sort_by="mkt_cap", desc=True, limit=2)
    assert [x["code"] for x in r["rows"]] == ["600519", "300750"]
    r = sc.screen(sort_by="pct_chg", desc=False, limit=500, exclude_suspended=False)
    s = json.dumps(r)  # NaN -> None must keep it serializable
    assert s


# ---------- SW transform ----------

def _sw_frame(rows):
    return pd.DataFrame(rows, columns=["symbol", "start_date",
                                       "industry_code", "update_time"])


def test_transform_latest_start_date_wins():
    df = _sw_frame([
        ("600519", "2020-01-01", "480000", "u"),
        ("600519", "2023-06-01", "340000", "u"),  # latest start_date wins
    ])
    assert ind._transform(df) == {"600519": "食品饮料"}


def test_transform_prefix_mapping_and_legacy():
    df = _sw_frame([
        ("600519", "2023-01-01", "340101", "u"),   # 34 食品饮料
        ("000001", "2023-01-01", "480101", "u"),   # 48 银行
        ("830799", "2023-01-01", "210101", "u"),   # legacy -> dropped
        ("300750", "2023-01-01", "630101", "u"),   # 63 电力设备
    ])
    m = ind._transform(df)
    assert m == {"600519": "食品饮料", "000001": "银行", "300750": "电力设备"}
    assert "830799" not in m  # legacy prefix -> unmapped


# ---------- industry_map persistence (non-blocking) ----------


def _write_industry(map_, fetched_at=None):
    rec = {"fetched_at": (fetched_at or datetime.now()).isoformat(),
           "map": map_}
    (data_dir() / "industry.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def _drain_refresh(timeout=5.0):
    """Wait for a background refresh to finish (or confirm none started)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with ind._refresh_lock:
            if not ind._refreshing:
                return True
        time.sleep(0.01)
    return False


def test_industry_fresh_file_no_fetch(monkeypatch):
    _write_industry({"600519": "白酒行业"})
    monkeypatch.setattr(ind, "_fetch_and_persist",
                        lambda: (_ for _ in ()).throw(AssertionError("fetch")))
    assert ind.industry_map()["600519"] == "白酒行业"
    assert _drain_refresh()


def test_industry_missing_file_returns_bundled_and_refreshes(monkeypatch):
    import threading
    done = threading.Event()
    monkeypatch.setattr(ind, "_fetch_and_persist",
                        lambda: done.set() or {"600519": "食品饮料"})
    m = ind.industry_map()
    assert m == ind._bundled()           # immediate, non-blocking
    assert done.wait(5)                  # refresh ran in background
    assert _drain_refresh()
    assert ind.industry_map()["600519"] == "食品饮料"  # cache swapped


def test_industry_concurrent_calls_one_refresh(monkeypatch):
    import threading
    started = threading.Event()
    calls = []
    def slow():
        started.set()
        calls.append(1)
        time.sleep(0.3)
        return {"600519": "食品饮料"}
    monkeypatch.setattr(ind, "_fetch_and_persist", slow)
    # first call schedules refresh; a second call while it runs must not
    ind.industry_map()
    assert started.wait(5)
    ind._cache = None                    # force re-evaluation
    ind._cache_ts = 0
    ind.industry_map()
    assert _drain_refresh()
    assert calls == [1]


def test_industry_stale_file_refresh_and_swap(monkeypatch):
    _write_industry({"600519": "old"}, fetched_at=datetime.now() - timedelta(days=8))
    import threading
    done = threading.Event()
    monkeypatch.setattr(ind, "_fetch_and_persist",
                        lambda: done.set() or {"600519": "new"})
    assert ind.industry_map()["600519"] == "old"   # stale file returned at once
    assert done.wait(5) and _drain_refresh()
    assert ind.industry_map()["600519"] == "new"


def test_industry_failure_keeps_stale(monkeypatch):
    _write_industry({"600519": "old"}, fetched_at=datetime.now() - timedelta(days=8))
    monkeypatch.setattr(ind, "_fetch_and_persist",
                        lambda: (_ for _ in ()).throw(RuntimeError("off")))
    assert ind.industry_map()["600519"] == "old"
    assert _drain_refresh()
    assert ind.industry_map()["600519"] == "old"  # still stale, not dropped


def test_industry_cache_revalidate_triggers_refresh(monkeypatch):
    """Cache older than 10 min re-checks the file and refreshes when stale."""
    _write_industry({"600519": "old"}, fetched_at=datetime.now() - timedelta(days=8))
    import threading
    done = threading.Event()
    monkeypatch.setattr(ind, "_fetch_and_persist",
                        lambda: done.set() or {"600519": "new"})
    ind._cache = {"600519": "old"}
    ind._cache_ts = time.time() - 601
    ind.industry_map()
    assert done.wait(5) and _drain_refresh()
    assert ind.industry_map()["600519"] == "new"


def test_industry_no_file_failure_bundled(monkeypatch):
    import threading
    done = threading.Event()
    def boom():
        done.set()
        raise RuntimeError("off")
    monkeypatch.setattr(ind, "_fetch_and_persist", boom)
    assert ind.industry_map() == ind._bundled()
    assert done.wait(5) and _drain_refresh()
    assert ind.industry_map() == ind._bundled()


def test_industry_throttled(monkeypatch):
    calls = []
    def boom():
        calls.append(1)
        raise RuntimeError("off")
    monkeypatch.setattr(ind, "_fetch_and_persist", boom)
    _write_industry({"600519": "old"}, fetched_at=datetime.now() - timedelta(days=8))
    ind.industry_map()
    assert _drain_refresh()
    ind._cache = None
    ind._cache_ts = 0
    ind.industry_map()  # second stale evaluation within 6 h -> no new thread
    assert _drain_refresh()
    assert calls == [1]
