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
    "last_trigger_check": None,
    "last_settlement_date": None,
    "last_error": None,
}


def _now() -> datetime:
    return datetime.now(_TZ)


def enabled() -> bool:
    return os.environ.get("ASHARE_WEB_SCHEDULER", "1").strip() != "0"


def status() -> dict[str, Any]:
    return {**_state, "enabled": enabled()}


# ---------- helpers injected from api.py (kept lazy to avoid circulars) ----------

def _accounts_ctx():
    """Return (store, lock_for, account_fn) from the api module."""
    from . import api
    return api._account_store(), api._lock_for, api._account


def _in_session(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
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
    return n


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


def _loop() -> None:
    while True:
        try:
            now = _now()
            if _in_session(now):
                trigger_tick()
            elif now.time() >= dtime(15, 35) and now.weekday() < 5 \
                    and _state["last_settlement_date"] != now.date().isoformat():
                settle_tick()
        except Exception as e:  # never crash the thread
            _state["last_error"] = str(e)
            log.exception("scheduler tick failed")
        time.sleep(60)


def start() -> None:
    if not enabled() or _state["enabled"]:
        return
    _state["enabled"] = True
    threading.Thread(target=_loop, daemon=True, name="ashare-scheduler").start()


def sync_main(argv: list[str] | None = None) -> None:
    """CLI: run the daily settlement + warm-up once."""
    import argparse
    p = argparse.ArgumentParser(prog="ashare-sync",
                                description="Run daily settlement now")
    p.add_argument("--force", action="store_true",
                   help="also skip the trading-day (holiday) check")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
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
