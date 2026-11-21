"""Bundled stock-list snapshot keeps search working when live sources are down."""
import pytest

import ashare_mcp.data.akshare_data as akd


@pytest.fixture
def all_sources_down(monkeypatch):
    for fn in ("stock_info_a_code_name", "stock_info_sh_name_code",
               "stock_info_sz_name_code", "stock_info_bj_name_code"):
        monkeypatch.setattr(akd.ak, fn,
                            lambda *a, **k: (_ for _ in ()).throw(
                                ConnectionError("down")))
    akd._caches.pop("stock_list", None)
    yield
    akd._caches.pop("stock_list", None)


def test_snapshot_has_full_coverage():
    df = akd._bundled_stock_list()
    assert len(df) > 5000
    assert set(df["market"].unique()) == {"sh", "sz", "bj"}


def test_search_falls_back_to_snapshot(all_sources_down):
    hits = akd.search_stock("茅台")
    assert hits and hits[0]["code"] == "600519"
    hits = akd.search_stock("600519")
    assert hits and hits[0]["code"] == "600519"
    hits = akd.search_stock("平安银行")
    assert any(h["code"] == "000001" for h in hits)
