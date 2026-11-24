"""Prewarm marker + gating logic (no real fetches)."""
from __future__ import annotations

import json
import time

import pytest

from ashare_mcp.web import scheduler


@pytest.fixture
def pw(tmp_path, monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_DATA_DIR", str(tmp_path))
    saved = dict(scheduler._prewarm)
    scheduler._prewarm.update(state="idle", step="", done=0, total=0,
                             finished_at=None, error=None)
    yield tmp_path
    scheduler._prewarm.clear()
    scheduler._prewarm.update(saved)


def test_marker_roundtrip(pw):
    assert scheduler._prewarm_due("2026-11-23") is True
    scheduler._prewarm_marker_path().write_text(
        json.dumps({"date": "2026-11-23"}), encoding="utf-8")
    assert scheduler._prewarm_due("2026-11-23") is False
    assert scheduler._prewarm_due("2026-11-24") is True


def test_skip_when_disabled(pw, monkeypatch):
    monkeypatch.setenv("ASHARE_PREWARM", "0")
    assert scheduler.prewarm_enabled() is False
    assert scheduler._maybe_prewarm("2026-11-23") is False
    assert scheduler._prewarm["state"] == "idle"


def test_maybe_prewarm_not_due(pw, monkeypatch):
    monkeypatch.setenv("ASHARE_PREWARM", "1")
    scheduler._prewarm_marker_path().write_text(
        json.dumps({"date": "2026-11-23"}), encoding="utf-8")
    assert scheduler._maybe_prewarm("2026-11-23") is False


def test_maybe_prewarm_starts_thread(pw, monkeypatch):
    monkeypatch.setenv("ASHARE_PREWARM", "1")
    ran = []
    monkeypatch.setattr(scheduler, "_prewarm_run", lambda: ran.append(1))
    assert scheduler._maybe_prewarm("2026-11-23") is True
    scheduler._prewarm_thread.join(timeout=5)
    assert ran == [1]


def test_status_exposes_prewarm(pw):
    st = scheduler.status()
    assert "prewarm" in st
    assert st["prewarm"]["state"] == "idle"


def test_backoff_after_error(pw, monkeypatch):
    monkeypatch.setenv("ASHARE_PREWARM", "1")

    def _boom(**kw):
        raise RuntimeError("net down")
    from ashare_mcp.data import akshare_data as ad
    monkeypatch.setattr(ad, "_spot_df", _boom)
    assert scheduler._maybe_prewarm("2026-11-23") is True
    scheduler._prewarm_thread.join(timeout=5)
    assert scheduler._prewarm["state"] == "error"
    assert scheduler._prewarm_backoff_until > time.monotonic()
    # still due but inside the backoff window: no retry
    assert scheduler._maybe_prewarm("2026-11-23") is False
    # once the deadline passes, a retry is allowed again
    scheduler._prewarm_backoff_until = 0.0
    ran = []
    monkeypatch.setattr(scheduler, "_prewarm_run",
                        lambda: ran.append(1))
    assert scheduler._maybe_prewarm("2026-11-23") is True
    scheduler._prewarm_thread.join(timeout=5)
    assert ran == [1]
