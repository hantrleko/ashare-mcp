"""Runtime configuration."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

# Anchor for "is this a source checkout": <repo>/src/ashare_mcp/config.py
# has pyproject.toml two levels up. Installed wheels do not, and their
# parents[3] would point inside the venv / uv cache — a bad place for
# user accounts. Tests may monkeypatch this path.
_PKG_FILE = Path(__file__).resolve()

_migrated = False


def user_data_dir() -> Path:
    """Per-user data dir for installed packages (desktop fallback too)."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "").strip()
        base = Path(appdata) if appdata else \
            Path.home() / "AppData" / "Roaming"
        return base / "ashare-mcp" / "data"
    return Path.home() / ".ashare-mcp"


def _uv_cache_dir() -> Path:
    env = os.environ.get("UV_CACHE_DIR", "").strip()
    if env:
        return Path(env)
    if os.name == "nt":
        la = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(la) if la else Path.home() / "AppData" / "Local"
        return base / "uv" / "cache"
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "uv"


def _is_source_checkout() -> bool:
    return (_PKG_FILE.parents[2] / "pyproject.toml").exists()


def _default_data_dir() -> Path:
    if _is_source_checkout():
        return _PKG_FILE.parents[3] / "data"
    return user_data_dir()


def _legacy_candidates() -> list[Path]:
    """Dirs that may hold a paper.db left by an earlier install."""
    cands = [_PKG_FILE.parents[3] / "data"]
    try:
        cands += sorted(_uv_cache_dir().glob("archive-v0/*/data"))
    except OSError:
        pass
    return cands


def _migrate_legacy(dest: Path) -> None:
    """One-shot copy of the newest legacy account store into ``dest``.

    Sources are never modified; any failure is logged and ignored.
    """
    best: tuple[float, Path] | None = None
    for d in _legacy_candidates():
        for name in ("paper.db", "paper_account.json"):
            f = d / name
            try:
                mt = f.stat().st_mtime
            except OSError:
                continue
            if best is None or mt > best[0]:
                best = (mt, f)
    if best is None:
        return
    src = best[1]
    try:
        dest.mkdir(parents=True, exist_ok=True)
        if src.name == "paper.db":
            for suffix in ("", "-wal", "-shm"):
                f = src.with_name(src.name + suffix)
                if f.exists():
                    shutil.copy2(f, dest / f.name)
        else:
            shutil.copy2(src, dest / src.name)
        log.info("migrated legacy accounts %s -> %s", src.parent, dest)
    except Exception:
        log.warning("legacy account migration failed: %s -> %s",
                    src.parent, dest, exc_info=True)


def data_dir() -> Path:
    """Directory for persisted state (paper account DB / caches)."""
    env = os.environ.get("ASHARE_MCP_DATA_DIR", "").strip()
    if env:
        p = Path(env).expanduser()
    else:
        global _migrated
        p = _default_data_dir()
        if not _migrated and not _is_source_checkout():
            _migrated = True
            try:
                if not (p / "paper.db").exists():
                    _migrate_legacy(p)
            except Exception:
                log.warning("legacy account migration failed",
                            exc_info=True)
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except OSError:
        fallback = Path.home() / ".ashare-mcp"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def tushare_token() -> str:
    return os.environ.get("TUSHARE_TOKEN", "").strip()
