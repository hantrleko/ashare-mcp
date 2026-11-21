"""Runtime configuration."""
from __future__ import annotations

import os
from pathlib import Path

# Paper-trading / persisted state directory.
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def data_dir() -> Path:
    """Directory for persisted state (paper account JSON)."""
    env = os.environ.get("ASHARE_MCP_DATA_DIR", "").strip()
    if env:
        p = Path(env).expanduser()
    else:
        p = _DEFAULT_DATA_DIR
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except OSError:
        fallback = Path.home() / ".ashare-mcp"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def tushare_token() -> str:
    return os.environ.get("TUSHARE_TOKEN", "").strip()
