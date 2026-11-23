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
    got = desktop._resolve_data_dir()
    assert got == tmp_path / "roam" / "ashare-mcp" / "data"


def test_data_dir_frozen_bad_json(tmp_path, monkeypatch):
    monkeypatch.delenv("ASHARE_MCP_DATA_DIR", raising=False)
    monkeypatch.setattr(desktop, "_frozen", lambda: True)
    monkeypatch.setattr(desktop, "_exe_dir", lambda: tmp_path)
    (tmp_path / "ashare-desktop.json").write_text("not json",
                                                 encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roam"))
    assert desktop._resolve_data_dir() == \
        tmp_path / "roam" / "ashare-mcp" / "data"


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
