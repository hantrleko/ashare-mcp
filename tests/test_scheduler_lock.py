"""Cross-process scheduler lock on data_dir/scheduler.lock."""
from __future__ import annotations

import time

import pytest

from ashare_mcp.web import scheduler


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_DATA_DIR", str(tmp_path))
    scheduler._release_lock()          # drop a stale handle a leaked
    scheduler._lock_wait_thread = None  # waiter may have grabbed
    yield tmp_path
    scheduler._release_lock()
    scheduler._lock_wait_thread = None
    scheduler._state["enabled"] = False
    scheduler._state["reason"] = None


def test_lock_excludes_second_handle(lock_dir):
    assert scheduler._acquire_lock() is True
    other = open(lock_dir / "scheduler.lock", "a+b")
    try:
        assert scheduler._try_lock_file(other) is False
    finally:
        other.close()


def test_second_process_attempt_fails_via_acquire(lock_dir, monkeypatch):
    assert scheduler._acquire_lock() is True
    # a fresh "process" view: pretend no held handle and try again on the
    # same file — the OS lock must refuse it.
    held = scheduler._lock_file
    scheduler._lock_file = None
    try:
        assert scheduler._acquire_lock() is False
    finally:
        scheduler._lock_file = held


def test_acquire_after_release(lock_dir):
    assert scheduler._acquire_lock() is True
    scheduler._release_lock()
    other = open(lock_dir / "scheduler.lock", "a+b")
    try:
        assert scheduler._try_lock_file(other) is True
        scheduler._unlock_file(other)
    finally:
        other.close()


def test_start_reports_reason_when_locked(lock_dir, monkeypatch):
    # hold the lock "from another process"
    other = open(lock_dir / "scheduler.lock", "a+b")
    assert scheduler._try_lock_file(other) is True
    monkeypatch.setenv("ASHARE_WEB_SCHEDULER", "1")
    # stub the loop so a waiter that slips an acquire in before teardown
    # cannot start real ticks in a later test's process
    monkeypatch.setattr(scheduler, "_loop", lambda: None)
    monkeypatch.setattr(scheduler, "_state", dict(scheduler._state, enabled=False, reason=None))
    try:
        scheduler.start()
        assert scheduler._state["enabled"] is False
        assert scheduler._state["reason"] == "另一个进程正在运行调度器"
        st = scheduler.status()
        assert st["enabled"] is False
        assert "另一个进程" in st["reason"]
    finally:
        # turn the scheduler off before freeing the lock so the spawned
        # waiter thread exits instead of acquiring it between tests
        monkeypatch.setenv("ASHARE_WEB_SCHEDULER", "0")
        scheduler._unlock_file(other)
        other.close()


def test_takeover_when_other_process_exits(lock_dir, monkeypatch):
    """Lock held by 'another process': start() waits; after release it
    takes over and runs _loop()."""
    other = open(lock_dir / "scheduler.lock", "a+b")
    assert scheduler._try_lock_file(other) is True
    monkeypatch.setenv("ASHARE_WEB_SCHEDULER", "1")
    monkeypatch.setattr(scheduler, "_LOCK_RETRY_SECS", 0.05)
    scheduler._lock_wait_thread = None
    ran = []
    monkeypatch.setattr(scheduler, "_loop", lambda: ran.append(True))
    monkeypatch.setattr(
        scheduler, "_state",
        dict(scheduler._state, enabled=False, reason=None))
    try:
        scheduler.start()
        st = scheduler.status()
        assert st["enabled"] is False
        assert "另一个进程" in st["reason"]

        # 'other process' exits -> the waiter takes over within ~2 s
        scheduler._unlock_file(other)
        other.close()
        other = None
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not scheduler._state["enabled"]:
            time.sleep(0.05)
        assert scheduler._state["enabled"] is True
        assert scheduler._state["reason"] is None
        assert ran  # stubbed _loop ran, no real ticks
        st = scheduler.status()
        assert st["enabled"] is True and st["reason"] is None
    finally:
        monkeypatch.setenv("ASHARE_WEB_SCHEDULER", "0")
        if other is not None:
            scheduler._unlock_file(other)
            other.close()
        scheduler._release_lock()
        t = scheduler._lock_wait_thread
        if t is not None:
            t.join(timeout=2)
        scheduler._state["enabled"] = False
        scheduler._state["reason"] = None
