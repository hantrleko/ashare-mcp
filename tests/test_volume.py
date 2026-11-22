"""Volume unit normalization: sina kline volume (shares) -> 手; EM keeps
手; market.db user_version=2 migration drops non-index cached bars."""
import sqlite3

import pandas as pd
import pytest

from ashare_mcp.data import akshare_data as akd
from ashare_mcp.data import store


def _sina_frame():
    return pd.DataFrame({
        "date": ["2024-01-02"],
        "open": [10.0], "high": [10.5], "low": [9.9], "close": [10.2],
        "volume": [12345600],          # shares
        "amount": [1.26e8],
        "outstanding_share": [1e9], "turnover": [0.012],
    })


def test_sina_kline_volume_shares_to_lots(monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_STORE", "0")
    import akshare as ak
    monkeypatch.setattr(ak, "stock_zh_a_hist_sina",
                        lambda **k: _sina_frame())
    recs = akd.get_kline("000858", start_date="20240101",
                         end_date="20240110")
    assert recs[0]["volume"] == pytest.approx(123456.0)  # /100 -> 手
    # turnover still scaled to %
    assert recs[0]["turnover"] == pytest.approx(1.2)


def test_em_kline_volume_untouched(monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_STORE", "0")
    import akshare as ak

    def _boom(**k):
        raise RuntimeError("sina down")
    monkeypatch.setattr(ak, "stock_zh_a_hist_sina", _boom)
    em = pd.DataFrame({
        "日期": ["2024-01-02"], "开盘": [10.0], "最高": [10.5],
        "最低": [9.9], "收盘": [10.2], "成交量": [123456],
        "成交额": [1.26e8], "振幅": [6.0], "涨跌幅": [2.0],
        "涨跌额": [0.2], "换手率": [1.2]})
    monkeypatch.setattr(ak, "stock_zh_a_hist_em", lambda **k: em)
    recs = akd.get_kline("000858", start_date="20240101",
                         end_date="20240110")
    assert recs[0]["volume"] == pytest.approx(123456.0)  # already 手


def test_store_migration_v2(tmp_path, monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_DATA_DIR", str(tmp_path))
    db = tmp_path / "market.db"
    conn = sqlite3.connect(db)
    conn.executescript(store._DDL)
    rows = [("600519", "qfq", "2024-01-02"),
            ("600519", "", "2024-01-02"),
            ("sh000300", "idx", "2024-01-02")]
    for k, a, d in rows:
        conn.execute(
            "INSERT INTO daily_bars VALUES (?,?,?,1,1,1,1,1,1,1,1,1,1)",
            (k, a, d))
        conn.execute(
            "INSERT INTO sync_meta VALUES (?,?,?,?,?)",
            (k, a, d, d, "now"))
    conn.commit()
    conn.close()

    store._conn().close()           # triggers migration
    conn = sqlite3.connect(db)
    left = {r[0] for r in conn.execute(
        "SELECT DISTINCT adjust FROM daily_bars")}
    assert left == {"idx"}           # stock rows deleted, index kept
    assert conn.execute(
        "SELECT COUNT(*) FROM daily_bars").fetchone()[0] == 1
    (v,) = conn.execute("PRAGMA user_version").fetchone()
    assert v >= 2
    conn.close()
    store._conn().close()           # idempotent: no error, still v2
    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT COUNT(*) FROM daily_bars").fetchone()[0] == 1
    conn.close()
