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
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
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


# ---------- tray notifications ----------

# WebView2 here auto-denies Notification.requestPermission() without firing
# PermissionRequested, so the desktop app sends Windows notifications itself:
# poll /api/events and show NotifyIcon balloon tips.
EVENTS_POLL_SECS = 30.0
EVENT_MAX_AGE = timedelta(hours=24)
EVENT_BATCH_MAX = 3


def _events_cursor_path() -> Path:
    d = _appdata() / "ashare-mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d / "events_cursor.txt"


def _read_cursor() -> str | None:
    try:
        s = _events_cursor_path().read_text(encoding="utf-8").strip()
        return s or None
    except OSError:
        return None


def _write_cursor(since: str) -> None:
    try:
        _events_cursor_path().write_text(since, encoding="utf-8")
    except OSError:
        pass


def _get_events(base_url: str, since: str | None,
                timeout: float = 5.0) -> dict | None:
    try:
        q = f"?since={urllib.parse.quote(since)}" if since else ""
        with urllib.request.urlopen(base_url + "/api/events" + q,
                                    timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _recent(events: list[dict], now_iso: str,
            max_age: timedelta = EVENT_MAX_AGE) -> list[dict]:
    """Events with `at` within max_age of the server's `now`."""
    try:
        now = datetime.fromisoformat(now_iso)
    except (TypeError, ValueError):
        return list(events)
    out = []
    for ev in events:
        try:
            at = datetime.fromisoformat(str(ev.get("at") or ""))
        except ValueError:
            continue
        if now - at <= max_age:
            out.append(ev)
    return out


def _event_text(ev: dict) -> tuple[str, str, str]:
    """(title, body, kind) — same wording as the web notification path."""
    side = {"buy": "买入", "sell": "卖出"}.get(ev.get("side"),
                                              ev.get("side") or "")
    px = ev.get("price") if ev.get("price") is not None \
        else ev.get("filled_price")
    body = (f"{ev.get('account_name') or ''} · "
            f"{ev.get('name') or ''} {ev.get('symbol') or ''} "
            f"{side} {ev.get('shares') or ''} 股"
            + (f" @ {px}" if px is not None else ""))
    if ev.get("kind") == "trigger_failed":
        err = ev.get("error")
        return "条件单失败", body + (f"（{err}）" if err else ""), "warn"
    return "条件单成交", body, "info"


def _balloon_plan(events: list[dict]) -> list[tuple[str, str, str]]:
    """One (title, body, kind) balloon per event, or a single batched one
    when more than EVENT_BATCH_MAX fired in one poll."""
    if len(events) > EVENT_BATCH_MAX:
        return [("条件单已触发", f"{len(events)} 笔条件单已触发", "info")]
    return [_event_text(ev) for ev in events]


def _ui_invoke(win, fn, timeout: float = 90.0) -> bool:
    """Run fn() on the WebView2 UI thread; retries while it initializes.

    pythonnet (``System``) only becomes importable once the winforms GUI
    thread has loaded the CLR, so the import itself is retried too.
    """
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            from System import Action
        except ImportError:
            time.sleep(1.0)
            continue
        native = getattr(win, "native", None)
        wv = getattr(native, "webview", None)
        if wv is not None:
            try:
                wv.Invoke(Action(fn))
                return True
            except Exception:
                time.sleep(1.0)
        else:
            time.sleep(0.5)
    return False


def _setup_tray(win, icon_path: Path) -> dict:
    """Create a NotifyIcon on the UI thread; returns a holder dict."""
    log = logging.getLogger(__name__)
    holder: dict = {}

    def _create() -> None:
        from System.Drawing import Icon, SystemIcons
        from System.Windows.Forms import NotifyIcon
        ni = NotifyIcon()
        try:
            ni.Icon = Icon(str(icon_path)) if icon_path.exists() \
                else SystemIcons.Application
        except Exception:
            ni.Icon = SystemIcons.Application
        ni.Text = TITLE
        ni.Visible = True

        def _clicked(_s, _e) -> None:
            try:
                win.restore()
                win.show()
                win.evaluate_js("location.hash='#/paper'")
                log.info("balloon clicked -> #/paper")
            except Exception:
                log.exception("balloon click handling failed")

        ni.BalloonTipClicked += _clicked
        holder["ni"] = ni
        holder["win"] = win
        log.info("tray icon ready")

    if _ui_invoke(win, _create):
        return holder
    log.warning("tray icon: webview UI thread never became available")
    return holder


def _tray_balloon(holder: dict, title: str, body: str,
                  kind: str = "info") -> None:
    ni = holder.get("ni")
    win = holder.get("win")
    if ni is None or win is None:
        return
    log = logging.getLogger(__name__)

    def _show() -> None:
        from System.Windows.Forms import ToolTipIcon
        ni.ShowBalloonTip(
            8000, title, body,
            ToolTipIcon.Warning if kind == "warn" else ToolTipIcon.Info)

    try:
        # NotifyIcon was created on the GUI thread; marshal the call back
        # onto it (cross-thread access can hang the WinForms loop).
        if _ui_invoke(win, _show, timeout=10.0):
            log.info("notify [%s] %s", title, body)
        else:
            log.warning("balloon skipped: UI thread busy")
    except Exception:
        log.exception("balloon failed")


def _dispose_tray(win, holder: dict) -> None:
    ni = holder.get("ni")
    if ni is None:
        return

    def _d() -> None:
        ni.Visible = False
        ni.Dispose()
    try:
        _ui_invoke(win, _d, timeout=5.0)
    except Exception:
        pass


def _events_loop(base_url: str, holder: dict, stop: threading.Event,
                 log) -> None:
    """Poll /api/events every 30 s.

    With no persisted cursor the first response only seeds it (old events
    never notify). With a persisted cursor, events missed while the app was
    closed are notified only if <24 h old; older ones just advance the
    cursor.
    """
    since = _read_cursor()
    first = since is None
    while not stop.is_set():
        r = _get_events(base_url, since)
        if r is not None:
            now = r.get("now")
            events = r.get("data") or []
            if not first:
                for title, body, kind in _balloon_plan(
                        _recent(events, now or "")):
                    try:
                        _tray_balloon(holder, title, body, kind)
                    except Exception:
                        log.exception("tray notify failed")
            first = False
            if now:
                since = now
                _write_cursor(since)
        stop.wait(EVENTS_POLL_SECS)


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

    if _frozen():
        # onedir datas land in sys._MEIPASS (the _internal dir)
        icon = Path(getattr(sys, "_MEIPASS", _exe_dir())) / "ashare.ico"
    else:
        icon = Path(__file__).resolve().parents[2] / "packaging" / \
            "ashare.ico"
    win = webview.create_window(
        TITLE, html=_LOADING_HTML, width=1440, height=900,
        min_size=(1024, 700), background_color="#070a10")

    def _load() -> None:
        if server is not None and not _wait_health(url):
            win.load_html(_error_html(log_path))
            return
        win.load_url(url)

    threading.Thread(target=_load, daemon=True).start()

    # Tray icon + condition-order event notifications (works in both
    # attach and own-backend mode; the events endpoint is the same app).
    stop_events = threading.Event()
    tray_holder: dict = {}

    def _tray_and_events() -> None:
        try:
            tray_holder.update(_setup_tray(win, icon))
        except Exception:
            log.exception("tray setup failed; notifications disabled")
        try:
            _events_loop(url, tray_holder, stop_events, log)
        except Exception:
            log.exception("events loop died")

    threading.Thread(target=_tray_and_events, daemon=True,
                     name="ashare-events").start()

    kwargs = dict(private_mode=False, storage_path=str(_webview_dir()),
                  gui="edgechromium")
    if icon.exists():
        import inspect
        if "icon" in inspect.signature(webview.start).parameters:
            kwargs["icon"] = str(icon)
    try:
        webview.start(**kwargs)
    finally:
        stop_events.set()
        _dispose_tray(win, tray_holder)
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
