"""Windows desktop app: pywebview window around the local web UI.

Launch modes:
- attach: if a healthy server on ASHARE_DESKTOP_ATTACH_PORT (default 8600)
  reports the same data dir, just open a window on it.
- own backend: otherwise run uvicorn in-process on 127.0.0.1:8601
  (8602-8609 only if 8601 is busy — WebView2 localStorage is per-origin,
  so a fixed port keeps watchlist/theme/presets stable across launches).

Single instance via a named mutex on Windows; a second launch focuses the
existing window and exits.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

TITLE = "A股研究台"
HOST = "127.0.0.1"
ATTACH_ENV = "ASHARE_DESKTOP_ATTACH_PORT"
DEFAULT_ATTACH_PORT = 8600
PORT_RANGE = range(8601, 8610)
HEALTH_TIMEOUT = 1.5
STARTUP_TIMEOUT = 90.0
MUTEX_NAME = "Local\\ashare-mcp-desktop"


def _appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or
                Path.home() / "AppData" / "Local")


def _log_dir() -> Path:
    d = _appdata() / "ashare-mcp" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _webview_dir() -> Path:
    d = _appdata() / "ashare-mcp" / "webview"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _exe_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _fix_stdio() -> Path:
    """Redirect None stdio (windowed exe) to a log file before imports log."""
    log_path = _log_dir() / "desktop.log"
    if sys.stdout is None or sys.stderr is None:
        f = open(log_path, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = f
        if sys.stderr is None:
            sys.stderr = f
    logging.basicConfig(
        filename=str(log_path), filemode="a", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8")
    return log_path


def _resolve_data_dir() -> Path | None:
    """Data dir to export via ASHARE_MCP_DATA_DIR, or None to leave unset.

    - env already set → None (respect it)
    - frozen exe → ashare-desktop.json next to the exe, else %APPDATA%
    - dev → None (package default is the repo's F:\\Hermes\\data)
    """
    if os.environ.get("ASHARE_MCP_DATA_DIR", "").strip():
        return None
    if not _frozen():
        return None
    cfg = _exe_dir() / "ashare-desktop.json"
    try:
        d = json.loads(cfg.read_text(encoding="utf-8")).get("data_dir")
        if d:
            return Path(d)
    except (OSError, ValueError):
        pass
    return Path(os.environ.get("APPDATA",
                              Path.home() / "AppData" / "Roaming")) / \
        "ashare-mcp" / "data"


def _our_data_dir() -> Path:
    """The data dir this process will actually use (post env setup)."""
    from ashare_mcp.config import data_dir
    return data_dir().resolve()


def _health(base_url: str, timeout: float = HEALTH_TIMEOUT) -> dict | None:
    try:
        with urllib.request.urlopen(base_url + "/api/health",
                                    timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _attach_url(health: dict | None, port: int,
                our_dir: Path) -> str | None:
    """URL to attach to, or None to start our own backend."""
    if not health or health.get("status") != "ok":
        return None
    dd = health.get("data_dir")
    if not dd:  # old server without data_dir: can't prove same dir
        return None
    try:
        if Path(dd).resolve() != our_dir.resolve():
            return None
    except OSError:
        return None
    return f"http://{HOST}:{port}"


def _port_free(port: int) -> bool:
    import socket
    with socket.socket() as s:
        try:
            s.bind((HOST, port))
        except OSError:
            return False
    return True


def _pick_port() -> tuple[int, bool]:
    """First free port in PORT_RANGE. Second element = preferred (8601)."""
    for i, p in enumerate(PORT_RANGE):
        if _port_free(p):
            return p, i == 0
    raise RuntimeError("8601-8609 all busy")


# ---------- Windows single instance ----------

def _acquire_mutex() -> bool:
    """True if we are the first instance (Windows only; True elsewhere)."""
    if os.name != "nt":
        return True
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW(None, False, MUTEX_NAME)
    return k32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def _focus_existing() -> None:
    if os.name != "nt":
        return
    import ctypes
    u32 = ctypes.windll.user32
    hwnd = u32.FindWindowW(None, TITLE)
    if hwnd:
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        u32.SetForegroundWindow(hwnd)


_LOADING_HTML = """<!doctype html><html><body style="margin:0;display:flex;
align-items:center;justify-content:center;height:100vh;background:#070a10;
color:#aab2c0;font-family:'Microsoft YaHei',sans-serif">
<div style="text-align:center"><div style="font-size:15px">正在启动 A股研究台…</div>
<div style="font-size:12px;color:#5b6478;margin-top:8px">首次启动可能需要一分钟</div>
</div></body></html>"""


def _error_html(log_path: Path) -> str:
    return f"""<!doctype html><html><body style="margin:0;display:flex;
align-items:center;justify-content:center;height:100vh;background:#070a10;
color:#aab2c0;font-family:'Microsoft YaHei',sans-serif">
<div style="text-align:center"><div style="font-size:15px;color:#ef5350">
启动超时</div><div style="font-size:12px;color:#5b6478;margin-top:8px">
日志:{log_path}</div></div></body></html>"""


def _wait_health(url: str, timeout: float = STARTUP_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _health(url) is not None:
            return True
        time.sleep(0.5)
    return False


def _start_backend(port: int):
    """Run uvicorn in a daemon thread; returns (server, thread)."""
    import uvicorn
    from ashare_mcp.web.api import app
    cfg = uvicorn.Config(app, host=HOST, port=port, log_config=None)
    server = uvicorn.Server(cfg)
    t = threading.Thread(target=server.run, daemon=True,
                         name="ashare-desktop-uvicorn")
    t.start()
    return server, t


def main() -> None:
    log_path = _fix_stdio()
    log = logging.getLogger(__name__)
    log.info("desktop start frozen=%s pid=%s", _frozen(), os.getpid())

    try:
        import webview
    except ImportError:
        msg = ("pywebview 未安装。开发模式请运行: "
               "uv run --extra desktop ashare-desktop")
        print(msg, file=sys.stderr)
        log.error(msg)
        raise SystemExit(msg)

    dd = _resolve_data_dir()
    if dd is not None:
        os.environ["ASHARE_MCP_DATA_DIR"] = str(dd)
    our_dir = _our_data_dir()
    log.info("data dir: %s", our_dir)

    if not _acquire_mutex():
        log.info("second instance -> focus existing window")
        _focus_existing()
        return

    attach_port = int(os.environ.get(ATTACH_ENV) or DEFAULT_ATTACH_PORT)
    base = f"http://{HOST}:{attach_port}"
    url = _attach_url(_health(base), attach_port, our_dir)

    server = None
    if url is None:
        port, preferred = _pick_port()
        if not preferred:
            log.warning("port %s busy, using %s — 界面设置(自选股/主题等) "
                        "按端口分别保存,将与平时不同", PORT_RANGE[0], port)
        url = f"http://{HOST}:{port}"
        server, server_t = _start_backend(port)
        log.info("own backend on %s", url)
    else:
        server_t = None
        log.info("attaching to %s", url)

    icon = _exe_dir() / "ashare.ico" if _frozen() else \
        Path(__file__).resolve().parents[2] / "packaging" / "ashare.ico"
    win = webview.create_window(
        TITLE, html=_LOADING_HTML, width=1440, height=900,
        min_size=(1024, 700), background_color="#070a10")

    def _load() -> None:
        if server is not None and not _wait_health(url):
            win.load_html(_error_html(log_path))
            return
        win.load_url(url)

    threading.Thread(target=_load, daemon=True).start()

    kwargs = dict(private_mode=False, storage_path=str(_webview_dir()),
                  gui="edgechromium")
    if icon.exists():
        import inspect
        if "icon" in inspect.signature(webview.start).parameters:
            kwargs["icon"] = str(icon)
    try:
        webview.start(**kwargs)
    finally:
        if server is not None:
            server.should_exit = True
            if server_t is not None:
                server_t.join(timeout=10)
        try:
            from ashare_mcp.web import scheduler
            scheduler.stop()
        except Exception:
            pass
        log.info("desktop exit")


if __name__ == "__main__":
    main()
