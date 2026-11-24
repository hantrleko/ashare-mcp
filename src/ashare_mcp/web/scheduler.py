"""Background scheduler: trigger checks in trading hours + daily settlement.

Started as a daemon thread from the FastAPI lifespan unless
``ASHARE_WEB_SCHEDULER=0``. The tick functions are also exposed for the
``ashare-sync`` CLI and for tests.

Loop (60 s):
- weekday 09:30-11:30 / 13:00-15:00 CST: check_triggers() for accounts
  that have pending triggers.
- once per day after 15:35 CST: if the SH index traded today, record each
  account's equity (status()) then warm the bar store for all held /
  triggered symbols and the index board.
"""
from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    _TZ = timezone(timedelta(hours=8))

_state: dict[str, Any] = {
    "enabled": False,
    "reason": None,
    "last_trigger_check": None,
    "last_settlement_date": None,
    "last_error": None,
}

# Open handle on data_dir/scheduler.lock, held for the process life so a
# second process on the same data dir cannot run the scheduler too.
_lock_file: Any = None


def _try_lock_file(f) -> bool:
    """Non-blocking exclusive lock on an open file object."""
    try:
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock_file(f) -> None:
    try:
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _acquire_lock() -> bool:
    """Take an exclusive non-blocking OS lock on the scheduler lock file."""
    global _lock_file
    if _lock_file is not None:
        return True
    from ..config import data_dir
    f = open(data_dir() / "scheduler.lock", "a+b")
    if not _try_lock_file(f):
        f.close()
        return False
    _lock_file = f
    atexit.register(_release_lock)
    return True


def _release_lock() -> None:
    global _lock_file
    f, _lock_file = _lock_file, None
    if f is None:
        return
    _unlock_file(f)
    f.close()


def _now() -> datetime:
    return datetime.now(_TZ)


def enabled() -> bool:
    return os.environ.get("ASHARE_WEB_SCHEDULER", "1").strip() != "0"


def status() -> dict[str, Any]:
    return {**_state, "enabled": enabled() and _state["enabled"],
            "prewarm": dict(_prewarm)}


# ---------- helpers injected from api.py (kept lazy to avoid circulars) ----------

def _accounts_ctx():
    """Return (store, lock_for, account_fn) from the api module."""
    from . import api
    return api._account_store(), api._lock_for, api._account


def _in_session(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    from ..data.calendar import is_trading_day
    if is_trading_day(now.date()) is False:
        return False  # weekday exchange holiday
    t = now.time()
    return dtime(9, 30) <= t <= dtime(11, 30) or dtime(13, 0) <= t <= dtime(15, 0)


def _pending_accounts(store) -> list[str]:
    out = []
    for a in store.list():
        try:
            st, _ = store.load(a["id"])
            if any(t.get("status") == "pending"
                   for t in st.get("triggers", [])):
                out.append(a["id"])
        except Exception:
            continue
    return out


def trigger_tick() -> int:
    """Check triggers for all accounts that have pending ones."""
    store, lock_for, account = _accounts_ctx()
    n = 0
    for aid in _pending_accounts(store):
        try:
            with lock_for(aid):
                account(aid).check_triggers()
            n += 1
        except Exception as e:
            _state["last_error"] = f"trigger {aid}: {e}"
            log.exception("trigger check failed for %s", aid)
    _state["last_trigger_check"] = _now().isoformat(timespec="seconds")
    # built-in arena agents: execute today's rebalance plan at/after 09:31
    try:
        from ..trading import house
        now = _now()

        def _locked_acct(aid: str):
            return _LockedHouseAcct(aid, lock_for(aid), account(aid))
        house.trigger_hook(now.strftime("%H:%M"), now.date(),
                           store, _locked_acct)
    except Exception as e:
        _state["last_error"] = f"house exec: {e}"
    return n


class _LockedHouseAcct:
    """Wraps PaperAccount so house trades run under the account lock."""
    def __init__(self, aid, lock, acct):
        self._aid, self._lock, self._acct = aid, lock, acct

    @property
    def state(self):
        # PaperAccount reloads state on every mutation; always read through
        return self._acct.state

    def __getattr__(self, k):
        return getattr(self._acct, k)
    def buy(self, *a, **kw):
        with self._lock:
            return self._acct.buy(*a, **kw)
    def sell(self, *a, **kw):
        with self._lock:
            return self._acct.sell(*a, **kw)
    def status(self):
        with self._lock:
            return self._acct.status()


def _traded_today(get_index_kline: Callable, today: str) -> bool:
    try:
        bars, _ = get_index_kline("sh000001")
        return bool(bars) and bars[-1].get("date") == today
    except Exception as e:
        _state["last_error"] = f"index check: {e}"
        log.exception("index holiday check failed")
        return False


def settle_tick(force: bool = False, get_index_kline: Callable | None = None,
                get_kline: Callable | None = None) -> dict[str, Any]:
    """Daily post-close job: equity snapshot + store warm-up.

    ``force`` skips both the in-memory once-per-day guard and the
    holiday check. Returns a small report dict.
    """
    from ..data.facade import market_data
    get_index_kline = get_index_kline or (
        lambda sym, **kw: market_data.call("get_index_kline", sym, **kw))
    get_kline = get_kline or (
        lambda sym, **kw: market_data.call("get_kline", sym, **kw))

    today = _now().date().isoformat()
    if not force:
        if _state["last_settlement_date"] == today:
            return {"skipped": "already ran today"}
        from ..data.calendar import is_trading_day
        if is_trading_day(_now().date()) is False:
            return {"skipped": "holiday"}
        if not _traded_today(get_index_kline, today):
            return {"skipped": "not a trading day"}

    store, lock_for, account = _accounts_ctx()
    symbols: set[str] = set()
    report: dict[str, Any] = {"accounts": [], "warmed": [], "errors": []}
    for a in store.list():
        aid = a["id"]
        try:
            with lock_for(aid):
                acct = account(aid)
                st = acct.status()
                report["accounts"].append({"id": aid, "equity": st["equity"]})
                stt, _ = store.load(aid)
                symbols |= set(stt.get("positions", {}).keys())
                symbols |= {t["symbol"] for t in stt.get("triggers", [])
                            if t.get("status") == "pending"}
        except Exception as e:
            _state["last_error"] = f"settle {aid}: {e}"
            report["errors"].append(f"{aid}: {e}")
            log.exception("settlement failed for %s", aid)

    # built-in arena agents: plan the next session's rebalance when it
    # opens a new week/month
    try:
        from ..trading import house
        house.settle_hook(_now().date(), store)
    except Exception as e:
        report["errors"].append(f"house plan: {e}")

    for sym in sorted(symbols):
        try:
            get_kline(sym, adjust="qfq", start_date="20200101")
            report["warmed"].append(sym)
            time.sleep(1)
        except Exception as e:
            report["errors"].append(f"{sym}: {e}")
    from .api import INDEX_BOARD
    for idx, _name in INDEX_BOARD:
        try:
            get_index_kline(idx)
            time.sleep(1)
        except Exception as e:
            report["errors"].append(f"{idx}: {e}")
    _state["last_settlement_date"] = today
    return report


# ---------------- background prewarm ----------------

_prewarm: dict[str, Any] = {"state": "idle", "step": "", "done": 0,
                           "total": 0, "finished_at": None, "error": None}
_prewarm_thread: threading.Thread | None = None
PREWARM_MARKER = "prewarm.json"
# After a failed run, do not retry for this long — during an outage the
# 60 s scheduler loop would otherwise hammer the sources.
PREWARM_BACKOFF_SECS = 30 * 60
_prewarm_backoff_until: float = 0.0  # time.monotonic() deadline
_prewarm_done_lock = threading.Lock()


def prewarm_enabled() -> bool:
    return os.environ.get("ASHARE_PREWARM", "1").strip() != "0"


def _prewarm_marker_path():
    from ..config import data_dir
    return data_dir() / PREWARM_MARKER


def _prewarm_marker() -> dict[str, Any]:
    try:
        import json
        return json.loads(_prewarm_marker_path().read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _prewarm_due(today_iso: str) -> bool:
    return _prewarm_marker().get("date") != today_iso


def _pw(step: str | None = None, done: int | None = None,
        total: int | None = None, state: str | None = None,
        error: str | None = None) -> None:
    if step is not None:
        _prewarm["step"] = step
    if done is not None:
        _prewarm["done"] = done
    if total is not None:
        _prewarm["total"] = total
    if state is not None:
        _prewarm["state"] = state
    if error is not None:
        _prewarm["error"] = error


def _prewarm_run() -> None:
    """Warm the caches most cold-start requests hit, once per day.

    Runs only inside the process that holds the scheduler lock (spawned
    from _loop / the takeover waiter).
    """
    from concurrent.futures import ThreadPoolExecutor
    import json
    today = _now().date().isoformat()
    counts: dict[str, Any] = {}
    _pw(state="running", step="spot", done=0, total=5, error=None)
    try:
        from ..data import akshare_data as ad
        spot = ad._spot_df()
        counts["spot_rows"] = int(len(spot))
        _pw(step="industry", done=1)
        from ..research import industry
        counts["industries"] = len(industry.industry_map())
        _pw(step="index", done=2)
        from .api import INDEX_BOARD
        from ..data.facade import market_data
        gik = lambda sym, **kw: market_data.call("get_index_kline", sym,
                                                 **kw)
        for idx, _name in INDEX_BOARD:
            gik(idx, period="daily")
        counts["indices"] = len(INDEX_BOARD)
        _pw(step="stocks", done=3)
        from ..trading import house
        uni = house._universe()
        codes = [str(c)[-6:] for c in uni["code6"]]
        counts["universe"] = len(codes)
        _prewarm["total"] = 4 + len(codes)
        warmed = [0]

        def _one(c: str) -> None:
            try:
                market_data.call("get_kline", c, period="daily",
                                 adjust="qfq")
            except Exception as e:
                log.debug("prewarm kline %s failed: %s", c, e)
            finally:
                with _prewarm_done_lock:
                    warmed[0] += 1
                    _pw(done=_prewarm["done"] + 1)

        with ThreadPoolExecutor(max_workers=2,
                                thread_name_prefix="prewarm") as ex:
            for c in codes:
                ex.submit(_one, c)
                time.sleep(0.3)
        counts["warmed"] = warmed[0]
        _pw(step="arena_preview")
        house.compute_preview()
        counts["arena_preview"] = True
        _prewarm_marker_path().write_text(
            json.dumps({"date": today, **counts}, ensure_ascii=False),
            encoding="utf-8")
        _pw(state="done", step="", done=_prewarm["total"])
        _prewarm["finished_at"] = _now().isoformat(timespec="seconds")
        log.info("prewarm done: %s", counts)
    except Exception as e:
        global _prewarm_backoff_until
        _prewarm_backoff_until = time.monotonic() + PREWARM_BACKOFF_SECS
        _pw(state="error", error=str(e))
        log.exception("prewarm failed; backing off %ds",
                      PREWARM_BACKOFF_SECS)


def _maybe_prewarm(today_iso: str) -> bool:
    """Start the once-a-day prewarm thread if due. Returns True if started."""
    global _prewarm_thread
    if not prewarm_enabled() or _prewarm["state"] == "running" \
            or time.monotonic() < _prewarm_backoff_until \
            or not _prewarm_due(today_iso):
        return False
    _prewarm_thread = threading.Thread(target=_prewarm_run, daemon=True,
                                       name="ashare-prewarm")
    _prewarm_thread.start()
    return True


def _loop() -> None:
    while True:
        try:
            now = _now()
            _maybe_prewarm(now.date().isoformat())
            if _in_session(now):
                trigger_tick()
            elif now.time() >= dtime(15, 35) and now.weekday() < 5 \
                    and _state["last_settlement_date"] != now.date().isoformat():
                settle_tick()
        except Exception as e:  # never crash the thread
            _state["last_error"] = str(e)
            log.exception("scheduler tick failed")
        time.sleep(60)


# Retry interval while waiting for another process to release the lock.
_LOCK_RETRY_SECS = 60.0
_lock_wait_thread: threading.Thread | None = None


def _wait_then_loop() -> None:
    """Retry the scheduler lock until it is free, then run the loop here."""
    global _lock_wait_thread
    try:
        while enabled() and not _state["enabled"]:
            if _acquire_lock():
                _state["enabled"] = True
                _state["reason"] = None
                log.info("scheduler lock acquired after wait; starting")
                _loop()
                return
            time.sleep(_LOCK_RETRY_SECS)
    finally:
        _lock_wait_thread = None


def start() -> None:
    global _lock_wait_thread
    if not enabled() or _state["enabled"]:
        return
    if not _acquire_lock():
        _state["reason"] = "另一个进程正在运行调度器"
        log.info("scheduler not started: %s", _state["reason"])
        if _lock_wait_thread is None or not _lock_wait_thread.is_alive():
            _lock_wait_thread = threading.Thread(
                target=_wait_then_loop, daemon=True,
                name="ashare-scheduler-wait")
            _lock_wait_thread.start()
        return
    _state["enabled"] = True
    _state["reason"] = None
    threading.Thread(target=_loop, daemon=True, name="ashare-scheduler").start()


def stop() -> None:
    _release_lock()


def sync_main(argv: list[str] | None = None) -> None:
    """CLI: run the daily settlement + warm-up once."""
    import argparse
    p = argparse.ArgumentParser(prog="ashare-sync",
                                description="Run daily settlement now")
    p.add_argument("--force", action="store_true",
                   help="also skip the trading-day (holiday) check")
    p.add_argument("--house", choices=["plan", "execute"],
                   help="run a built-in arena-agent action instead "
                        "of the daily settlement")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if args.house:
        from ..trading import house
        today = _now().date()
        if args.house == "plan":
            print(house.run_plans(today, force=args.force))
        else:
            print(house.run_executes(today, force=args.force))
        return
    today = _now().date().isoformat()
    if args.force:
        res = settle_tick(force=True)
    else:
        from ..data.facade import market_data
        gik = lambda sym, **kw: market_data.call("get_index_kline", sym, **kw)
        if not _traded_today(gik, today):
            print(f"{today}: not a trading day — nothing to do "
                  "(use --force to run anyway)")
            return
        res = settle_tick(force=True)
    print(res)


if __name__ == "__main__":
    sync_main()
