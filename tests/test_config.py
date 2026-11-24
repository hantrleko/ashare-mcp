"""Data-dir resolution for source checkouts vs installed packages."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import ashare_mcp.config as config


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Installed-mode anchor + isolated HOME-ish roots (no real env dir)."""
    monkeypatch.delenv("ASHARE_MCP_DATA_DIR", raising=False)
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    pkg = tmp_path / "site-packages" / "ashare_mcp" / "config.py"
    monkeypatch.setattr(config, "_PKG_FILE", pkg)
    saved = config._migrated
    config._migrated = False
    yield tmp_path
    config._migrated = saved


def test_env_wins(tmp_path, monkeypatch):
    env_dir = tmp_path / "custom"
    monkeypatch.setenv("ASHARE_MCP_DATA_DIR", str(env_dir))
    assert config.data_dir() == env_dir


def test_source_checkout_keeps_repo_data(tmp_path, monkeypatch):
    monkeypatch.delenv("ASHARE_MCP_DATA_DIR", raising=False)
    # fake checkout: <root>/proj/src/pkg/config.py + <root>/proj/pyproject.toml
    root = tmp_path / "outer" / "proj"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "pyproject.toml").write_text("x")
    monkeypatch.setattr(config, "_PKG_FILE",
                        root / "src" / "pkg" / "config.py")
    assert config.data_dir() == root.parent / "data"


def test_installed_uses_user_dir(cfg, monkeypatch):
    monkeypatch.setattr(config, "user_data_dir",
                        lambda: cfg / "userdir" / "data")
    assert config.data_dir() == cfg / "userdir" / "data"


def test_migration_copies_newest_legacy(cfg, monkeypatch):
    new = cfg / "appdata" / "ashare-mcp" / "data"
    monkeypatch.setattr(config, "user_data_dir", lambda: new)
    uv = cfg / "uvcache"
    monkeypatch.setattr(config, "_uv_cache_dir", lambda: uv)
    old1 = uv / "archive-v0" / "aaa" / "data"
    old2 = uv / "archive-v0" / "bbb" / "data"
    old1.mkdir(parents=True)
    old2.mkdir(parents=True)
    (old1 / "paper.db").write_bytes(b"old")
    (old2 / "paper.db").write_bytes(b"new")
    (old2 / "paper.db-wal").write_bytes(b"wal")
    # make old1 look older
    past = time.time() - 3600
    os.utime(old1 / "paper.db", (past, past))
    assert config.data_dir() == new
    assert (new / "paper.db").read_bytes() == b"new"
    assert (new / "paper.db-wal").read_bytes() == b"wal"
    # sources untouched
    assert (old2 / "paper.db").read_bytes() == b"new"
    assert (old1 / "paper.db").read_bytes() == b"old"


def test_migration_json_fallback(cfg, monkeypatch):
    new = cfg / "appdata" / "ashare-mcp" / "data"
    monkeypatch.setattr(config, "user_data_dir", lambda: new)
    # legacy candidate (a): _PKG_FILE.parents[3]/"data" == cfg.parent/"data"
    legacy = (cfg / ".." / "data").resolve()
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "paper_account.json").write_text("{}")
    monkeypatch.setattr(config, "_uv_cache_dir",
                        lambda: cfg / "missing-uv")
    assert config.data_dir() == new
    assert (new / "paper_account.json").exists()


def test_no_migration_when_db_exists(cfg, monkeypatch):
    new = cfg / "appdata" / "ashare-mcp" / "data"
    new.mkdir(parents=True)
    (new / "paper.db").write_bytes(b"current")
    monkeypatch.setattr(config, "user_data_dir", lambda: new)
    uv = cfg / "uvcache"
    (uv / "archive-v0" / "x" / "data").mkdir(parents=True)
    (uv / "archive-v0" / "x" / "data" / "paper.db").write_bytes(b"legacy")
    monkeypatch.setattr(config, "_uv_cache_dir", lambda: uv)
    assert config.data_dir() == new
    assert (new / "paper.db").read_bytes() == b"current"


def test_migration_failure_does_not_raise(cfg, monkeypatch):
    monkeypatch.setattr(config, "user_data_dir",
                        lambda: cfg / "appdata" / "data")
    monkeypatch.setattr(config, "_legacy_candidates",
                        lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert config.data_dir() == cfg / "appdata" / "data"
