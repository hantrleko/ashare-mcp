"""Pure-logic tests for the desktop launcher (no pywebview needed)."""
from __future__ import annotations

import socket
from pathlib import Path

import pytest

from ashare_mcp import desktop


# ---------- data-dir resolution ----------

def test_data_dir_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_DATA_DIR", str(tmp_path))
    assert desktop._resolve_data_dir() is None


def test_data_dir_dev_default(monkeypatch):
    monkeypatch.delenv("ASHARE_MCP_DATA_DIR", raising=False)
    monkeypatch.setattr(desktop, "_frozen", lambda: False)
    assert desktop._resolve_data_dir() is None


def test_data_dir_frozen_json(tmp_path, monkeypatch):
    monkeypatch.delenv("ASHARE_MCP_DATA_DIR", raising=False)
    monkeypatch.setattr(desktop, "_frozen", lambda: True)
    monkeypatch.setattr(desktop, "_exe_dir", lambda: tmp_path)
    (tmp_path / "ashare-desktop.json").write_text(
        '{"data_dir": "F:\\\\Hermes\\\\data"}', encoding="utf-8")
    assert desktop._resolve_data_dir() == Path("F:\\Hermes\\data")


def test_data_dir_frozen_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("ASHARE_MCP_DATA_DIR", raising=False)
    monkeypatch.setattr(desktop, "_frozen", lambda: True)
    monkeypatch.setattr(desktop, "_exe_dir", lambda: tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roam"))
    from ashare_mcp.config import user_data_dir
    assert desktop._resolve_data_dir() == user_data_dir()


def test_data_dir_frozen_bad_json(tmp_path, monkeypatch):
    monkeypatch.delenv("ASHARE_MCP_DATA_DIR", raising=False)
    monkeypatch.setattr(desktop, "_frozen", lambda: True)
    monkeypatch.setattr(desktop, "_exe_dir", lambda: tmp_path)
    (tmp_path / "ashare-desktop.json").write_text("not json",
                                                 encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roam"))
    from ashare_mcp.config import user_data_dir
    assert desktop._resolve_data_dir() == user_data_dir()


# ---------- attach decision ----------

def _dd(tmp_path, name="data"):
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return p.resolve()


def test_attach_same_dir(tmp_path):
    our = _dd(tmp_path)
    url = desktop._attach_url(
        {"status": "ok", "data_dir": str(our)}, 8600, our)
    assert url == "http://127.0.0.1:8600"


def test_attach_different_dir(tmp_path):
    our = _dd(tmp_path)
    other = _dd(tmp_path, "other")
    url = desktop._attach_url(
        {"status": "ok", "data_dir": str(other)}, 8600, our)
    assert url is None


def test_attach_old_server_no_field(tmp_path):
    our = _dd(tmp_path)
    assert desktop._attach_url({"status": "ok"}, 8600, our) is None


def test_attach_unreachable(tmp_path):
    our = _dd(tmp_path)
    assert desktop._attach_url(None, 8600, our) is None


# ---------- port selection ----------

def test_pick_port_preferred_free():
    port, preferred = desktop._pick_port()
    assert port == desktop.PORT_RANGE[0] and preferred is True


def test_pick_port_skips_busy():
    s = socket.socket()
    s.bind(("127.0.0.1", desktop.PORT_RANGE[0]))
    s.listen(1)
    try:
        port, preferred = desktop._pick_port()
        assert port == desktop.PORT_RANGE[0] + 1
        assert preferred is False
    finally:
        s.close()


def test_event_text():
    from ashare_mcp.desktop import _event_text
    t, b, k = _event_text({"kind": "trigger_filled", "account_name": "示例",
                           "name": "贵州茅台", "symbol": "600519", "side": "buy",
                           "shares": 100, "filled_price": 1700.5, "price": None})
    assert (t, k) == ("条件单成交", "info")
    assert "示例" in b and "贵州茅台" in b and "买入" in b
    assert "100" in b and "1700.5" in b
    t, b, k = _event_text({"kind": "trigger_failed", "account_name": "a",
                           "name": "n", "symbol": "000001", "side": "sell",
                           "shares": 200, "error": "涨停"})
    assert (t, k) == ("条件单失败", "warn")
    assert "卖出" in b and "涨停" in b
def test_event_recent_filter():
    from ashare_mcp.desktop import _recent
    evs = [{"at": "2026-11-23T10:00:00"},
           {"at": "2026-11-22T10:00:00"},   # 24h ago -> borderline kept
           {"at": "2026-11-20T10:00:00"},   # older -> dropped
           {"at": "bad"}]
    out = _recent(evs, "2026-11-23T09:00:00")
    assert [e["at"] for e in out] == ["2026-11-23T10:00:00",
                                    "2026-11-22T10:00:00"]
    # unparseable now -> everything passes through
    assert len(_recent(evs, "not-a-date")) == 4


def test_balloon_plan_batching():
    from ashare_mcp.desktop import _balloon_plan
    ev = lambda i: {"kind": "trigger_filled", "account_name": "a",
                    "name": "n", "symbol": f"00000{i}", "side": "buy",
                    "shares": 100, "price": 10.0}
    assert len(_balloon_plan([ev(1), ev(2), ev(3)])) == 3
    plan = _balloon_plan([ev(i) for i in range(4)])
    assert plan == [("条件单已触发", "4 笔条件单已触发", "info")]


def test_event_text_titles():
    from ashare_mcp.desktop import _event_text
    t, b, k = _event_text({"kind": "trigger_filled", "account_name": "示例",
                           "name": "贵州茅台", "symbol": "600519", "side": "buy",
                           "shares": 100, "filled_price": 1700.5, "price": None})
    assert (t, k) == ("条件单成交", "info")
    assert "示例" in b and "贵州茅台" in b and "买入" in b
    assert "100" in b and "1700.5" in b
    t, b, k = _event_text({"kind": "trigger_failed", "account_name": "a",
                           "name": "n", "symbol": "000001", "side": "sell",
                           "shares": 200, "error": "涨停"})
    assert (t, k) == ("条件单失败", "warn")
    assert "卖出" in b and "涨停" in b