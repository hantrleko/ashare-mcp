"""Shared test fixtures: keep all persisted state in tmp dirs, offline."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ASHARE_MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ASHARE_WEB_SCHEDULER", "0")
