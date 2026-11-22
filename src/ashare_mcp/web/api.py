"""FastAPI backend for the ashare-mcp web frontend.

Serves /api/* JSON endpoints backed by the market-data facade, the paper
trading account and the backtest engine, plus the built SPA from web/dist
(with client-side-routing fallback to index.html).

Run: ``python -m ashare_mcp.web`` (uvicorn, default http://127.0.0.1:8600).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..backtest.engine import STRATEGIES, run_backtest
from ..data.facade import market_data
from ..trading.accounts import AccountStore
from ..trading.paper import PaperAccount

# Same board as the Streamlit app (红涨绿跌 UI convention lives in the frontend).
INDEX_BOARD = [
    ("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指"),
    ("sh000300", "沪深300"), ("sh000688", "科创50"), ("sh000016", "上证50"),
    ("sh000905", "中证500"), ("sh000852", "中证1000"), ("bj899050", "北证50"),
]

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------- tiny in-process TTL cache ----------

class _Cache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any, ttl: float, loader: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._store.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        val = loader()
        with self._lock:
            self._store[key] = (now, val)
        return val


_cache = _Cache()
TTL_QUOTE = 15.0        # quote / quotes / indices
TTL_INTRADAY = 30.0     # minute bars
TTL_SLOW = 600.0        # kline / financial / factor / statements


def _call(name: str, *args: Any, ttl: float = 0.0, **kwargs: Any) -> tuple[Any, str]:
    def load() -> tuple[Any, str]:
        return market_data.call(name, *args, **kwargs)
    if ttl <= 0:
        return load()
    key_args = tuple(tuple(a) if isinstance(a, list) else a for a in args)
    return _cache.get((name, key_args, tuple(sorted(kwargs.items()))), ttl, load)


# ---------- auth + rate limiting (public mode only) ----------

PUBLIC = os.environ.get("ASHARE_WEB_PUBLIC") == "1"
_ADMIN_KEY = os.environ.get("ASHARE_ADMIN_KEY", "")

# token-bucket limits (per minute)
RATE_MUT = 30      # mutations, keyed by API key else IP
RATE_HEAVY = 6     # /api/screen + /api/backtest* per IP
RATE_GET = 120     # other GETs per IP

_buckets: dict[tuple[str, str], list[float]] = {}
_buckets_lock = threading.Lock()


def _bucket(key: tuple[str, str], limit: int, now: float) -> float:
    """Token bucket: returns seconds to wait, or 0.0 when allowed."""
    with _buckets_lock:
        cutoff = now - 60.0
        if len(_buckets) > 10_000:
            for k in [k for k, v in _buckets.items() if not v or v[-1] < cutoff]:
                del _buckets[k]
        hits = _buckets.setdefault(key, [])
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= limit:
            return max(hits[0] + 60.0 - now, 1.0)
        hits.append(now)
        return 0.0


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _role(request: Request) -> tuple[str, str | None]:
    """(role, account_id) — admin | agent | anonymous."""
    raw = _bearer(request)
    if not raw:
        return "anonymous", None
    if _ADMIN_KEY and hmac.compare_digest(raw, _ADMIN_KEY):
        return "admin", None
    acct = _account_store().verify_key(raw)
    return ("agent", acct) if acct else ("anonymous", None)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _require_mutation(request: Request, account: str | None,
                      account_scoped: bool = True) -> None:
    """Public-mode guard for mutating endpoints (no-op locally)."""
    if not PUBLIC:
        return
    role, key_acct = _role(request)
    if role == "admin":
        return
    if role == "anonymous":
        raise HTTPException(401, "需要 API Key（Authorization: Bearer …）")
    if not account_scoped:
        raise HTTPException(403, "agent key 无权执行该操作")
    if key_acct != (account or "default"):
        raise HTTPException(403, "agent key 只能操作自己的账户")


def _err(e: Exception) -> HTTPException:
    if isinstance(e, (ValueError, KeyError)):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=502, detail=f"upstream data failure: {e}")


def _run(fn: Callable[..., Any], *args: Any, ttl: float = 0.0, **kwargs: Any) -> Any:
    """Call a data function; every data response carries ``source``."""
    try:
        res, source = _call(fn.__name__ if callable(fn) else fn,
                            *args, ttl=ttl, **kwargs)
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)
    return {"data": res, "source": source}


# ---------- paper accounts (per-id cache + per-id lock) ----------

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_accts: dict[str, PaperAccount] = {}
_store: "AccountStore | None" = None


def _account_store() -> "AccountStore":
    global _store
    if _store is None:
        _store = AccountStore()
    return _store


def _lock_for(account: str) -> threading.Lock:
    with _locks_guard:
        if account not in _locks:
            _locks[account] = threading.Lock()
        return _locks[account]


def _account(account: str = "default") -> PaperAccount:
    with _locks_guard:
        if account not in _accts:
            _accts[account] = PaperAccount(account, _account_store())
        return _accts[account]


def _mutate(fn: Callable[..., Any], *args: Any, account: str = "default",
            **kwargs: Any) -> Any:
    """Run ``fn(acct, *args)`` under the account's lock.

    ``fn`` is an unbound PaperAccount method; the account is resolved
    inside the try so an unknown id maps to 404 rather than 502.
    """
    try:
        acct = _account(account)
        with _lock_for(account):
            return fn(acct, *args, **kwargs)
    except HTTPException:
        raise
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        code = 409 if "concurrently" in str(e) or "已被" in str(e) else 502
        raise HTTPException(status_code=code, detail=str(e))
    except Exception as e:
        raise _err(e)


class TradeIn(BaseModel):
    symbol: str
    shares: int
    reason: str = ""


class TriggerIn(BaseModel):
    symbol: str
    side: str
    shares: int
    trigger_price: float
    condition: str = ">="
    note: str = ""
    reason: str = ""


class ResetIn(BaseModel):
    capital: float = 1_000_000.0


class BacktestIn(BaseModel):
    symbol: str
    strategy: str = "ma_cross"
    params: dict[str, Any] = Field(default_factory=dict)
    start: str = ""
    end: str = ""
    capital: float = 1_000_000.0
    slippage_bps: float = 0.0
    min_trade_value: float = 5000.0


class PortfolioIn(BaseModel):
    symbols: list[str]
    weighting: str = "equal"
    rebalance: str = "M"
    start: str = ""
    end: str = ""
    capital: float = 1_000_000.0
    slippage_bps: float = 0.0
    min_trade_value: float = 5000.0
    benchmark: str = "sh000300"


class ScanIn(BaseModel):
    symbol: str
    strategy: str = "ma_cross"
    grid: dict[str, list[float]] = Field(default_factory=dict)
    start: str = ""
    end: str = ""
    split: float = 0.7
    metric: str = "sharpe"
    capital: float = 1_000_000.0
    slippage_bps: float = 0.0
    min_trade_value: float = 5000.0


class ScreenIn(BaseModel):
    ranges: dict[str, list[float | None]] = Field(default_factory=dict)
    industries: list[str] = Field(default_factory=list)
    boards: list[str] = Field(default_factory=list)
    exclude_st: bool = True
    exclude_suspended: bool = True
    momentum: dict[str, list[float | None]] = Field(default_factory=dict)
    sort_by: str = "mkt_cap"
    desc: bool = True
    limit: int = 100


# ---------- app ----------

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if PUBLIC and not _ADMIN_KEY:
        raise RuntimeError(
            "ASHARE_WEB_PUBLIC=1 requires ASHARE_ADMIN_KEY to be set")
    from . import scheduler
    scheduler.start()
    yield


app = FastAPI(title="ashare-mcp web", version="0.4.0", lifespan=_lifespan)


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    if not PUBLIC:
        return await call_next(request)
    path = request.url.path
    now = time.monotonic()
    ip = _client_ip(request)
    if path == "/api/screen" or path.startswith("/api/backtest"):
        wait = _bucket(("heavy", ip), RATE_HEAVY, now)
    elif request.method != "GET":
        # only a verified key gets its own bucket; anything else counts per IP
        role, acct = _role(request)
        ident = ("admin" if role == "admin" else acct) or ip
        wait = _bucket(("mut", ident), RATE_MUT, now)
    else:
        wait = _bucket(("get", ip), RATE_GET, now)
    if wait > 0:
        return JSONResponse(status_code=429,
                            content={"detail": "请求过于频繁，请稍后重试"},
                            headers={"Retry-After": str(int(wait) + 1)})
    return await call_next(request)


@app.exception_handler(Exception)
def _unhandled(request, exc):  # noqa: ANN001
    return JSONResponse(status_code=502,
                        content={"detail": f"upstream data failure: {exc}"})


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "providers": market_data.provider_status()}


@app.get("/api/search")
def search(q: str = "", limit: int = 10) -> dict[str, Any]:
    if not q.strip():
        raise HTTPException(400, "q is required")
    return _run("search_stock", q.strip(), max(1, min(int(limit), 50)),
                ttl=TTL_SLOW)


@app.get("/api/quote/{symbol}")
def quote(symbol: str) -> dict[str, Any]:
    return _run("get_quote", symbol, ttl=TTL_QUOTE)


@app.get("/api/quotes")
def quotes(symbols: str = "") -> dict[str, Any]:
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    if not syms:
        raise HTTPException(400, "symbols is required (comma separated)")
    return _run("get_quotes", syms[:50], ttl=TTL_QUOTE)


@app.get("/api/kline/{symbol}")
def kline(symbol: str, period: str = "daily", start: str = "",
          end: str = "", adjust: str = "qfq") -> dict[str, Any]:
    return _run("get_kline", symbol, period=period, start_date=start,
                end_date=end, adjust=adjust, ttl=TTL_SLOW)


@app.get("/api/indices")
def indices() -> dict[str, Any]:
    out = []
    source = ""
    for sym, name in INDEX_BOARD:
        try:
            q, source = _call("get_index_quote", sym, ttl=TTL_QUOTE)
            q = dict(q)
            q.setdefault("name", name)
            q.setdefault("symbol", sym)
            out.append(q)
        except Exception:
            continue
    return {"data": out, "source": source}


@app.get("/api/index-kline/{symbol}")
def index_kline(symbol: str, period: str = "daily",
                start: str = "") -> dict[str, Any]:
    return _run("get_index_kline", symbol, period=period, start_date=start,
                ttl=TTL_SLOW)


@app.get("/api/intraday/{symbol}")
def intraday(symbol: str) -> dict[str, Any]:
    return _run("get_intraday", symbol, ttl=TTL_INTRADAY)


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    return _run("get_market_overview", ttl=TTL_SLOW)


@app.get("/api/limit-pool")
def limit_pool(pool: str = "zt", date: str = "") -> dict[str, Any]:
    return _run("get_limit_pool", date, pool, 200, ttl=TTL_SLOW)


@app.get("/api/money-flow/{symbol}")
def money_flow(symbol: str, days: int = 30) -> dict[str, Any]:
    return _run("get_money_flow", symbol, int(days), ttl=TTL_SLOW)


@app.get("/api/financial/{symbol}")
def financial(symbol: str, indicator: str = "按报告期") -> dict[str, Any]:
    return _run("get_financial_abstract", symbol, indicator, 12, ttl=TTL_SLOW)


@app.get("/api/statement/{symbol}")
def statement(symbol: str, type: str = "income") -> dict[str, Any]:
    if type not in ("income", "balance", "cashflow"):
        raise HTTPException(400, "type must be income|balance|cashflow")
    return _run("get_financial_statement", symbol, type, 8, ttl=TTL_SLOW)


@app.get("/api/factor/{symbol}")
def factor(symbol: str) -> dict[str, Any]:
    return _run("get_factor_snapshot", symbol, 250, ttl=TTL_SLOW)


@app.get("/api/announcements")
def announcements(symbol: str = "", date: str = "") -> dict[str, Any]:
    return _run("get_announcements", symbol, date, 50, ttl=TTL_SLOW)


@app.get("/api/earnings")
def earnings(report_date: str = "", kind: str = "yjbb") -> dict[str, Any]:
    return _run("get_earnings_calendar", report_date, kind, 500, ttl=TTL_SLOW)


# ---------- paper trading ----------

@app.get("/api/paper/status")
def paper_status(account: str = "default") -> dict[str, Any]:
    return _mutate(PaperAccount.status, account=account)


@app.get("/api/paper/positions")
def paper_positions(account: str = "default") -> dict[str, Any]:
    return {"data": _mutate(PaperAccount.positions, account=account)}


@app.get("/api/paper/orders")
def paper_orders(limit: int = 50, account: str = "default") -> dict[str, Any]:
    return {"data": _mutate(PaperAccount.orders, limit, account=account)}


@app.get("/api/paper/triggers")
def paper_triggers(account: str = "default") -> dict[str, Any]:
    return {"data": _mutate(PaperAccount.triggers, account=account)}


@app.get("/api/paper/history")
def paper_history(account: str = "default") -> dict[str, Any]:
    return {"data": _mutate(PaperAccount.history, account=account)}


@app.post("/api/paper/buy")
def paper_buy(body: TradeIn, request: Request,
              account: str = "default") -> dict[str, Any]:
    _require_mutation(request, account)
    return _mutate(PaperAccount.buy, body.symbol, body.shares,
                   reason=body.reason, account=account)


@app.post("/api/paper/sell")
def paper_sell(body: TradeIn, request: Request,
               account: str = "default") -> dict[str, Any]:
    _require_mutation(request, account)
    return _mutate(PaperAccount.sell, body.symbol, body.shares,
                   reason=body.reason, account=account)


@app.post("/api/paper/triggers")
def paper_add_trigger(body: TriggerIn, request: Request,
                      account: str = "default") -> dict[str, Any]:
    _require_mutation(request, account)
    return _mutate(PaperAccount.add_trigger, body.symbol, body.side,
                   body.shares, body.trigger_price, body.condition,
                   body.note, body.reason, account=account)


@app.delete("/api/paper/triggers/{trigger_id}")
def paper_cancel_trigger(trigger_id: str, request: Request,
                         account: str = "default") -> dict[str, Any]:
    _require_mutation(request, account)
    return _mutate(PaperAccount.cancel_trigger, trigger_id,
                   account=account)


@app.post("/api/paper/check")
def paper_check(request: Request, account: str = "default") -> dict[str, Any]:
    _require_mutation(request, account)
    return _mutate(PaperAccount.check_triggers, account=account)


@app.post("/api/paper/reset")
def paper_reset(body: ResetIn, request: Request,
                account: str = "default") -> dict[str, Any]:
    _require_mutation(request, account)
    return _mutate(PaperAccount.reset, body.capital, account=account)


# ---------- accounts ----------

class AccountIn(BaseModel):
    name: str
    capital: float = 1_000_000.0
    id: str | None = None


class RenameIn(BaseModel):
    name: str


def _store_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/accounts")
def accounts_list() -> dict[str, Any]:
    _account("default")  # ensure the default account exists before listing
    return {"data": _account_store().list()}


@app.post("/api/accounts")
def accounts_create(body: AccountIn, request: Request) -> dict[str, Any]:
    _require_mutation(request, None, account_scoped=False)
    return _store_call(_account_store().create, body.name, body.capital,
                       body.id or None)


@app.patch("/api/accounts/{account_id}")
def accounts_rename(account_id: str, body: RenameIn,
                    request: Request) -> dict[str, Any]:
    _require_mutation(request, account_id)
    return _store_call(_account_store().rename, account_id, body.name)


@app.delete("/api/accounts/{account_id}")
def accounts_delete(account_id: str, request: Request) -> dict[str, Any]:
    _require_mutation(request, None, account_scoped=False)
    res = _store_call(_account_store().delete, account_id)
    with _locks_guard:
        _accts.pop(account_id, None)
        _locks.pop(account_id, None)
    return res


# ---------- scheduler ----------

# ---------- auth / arena ----------

@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    role, acct = _role(request)
    return {"public": PUBLIC, "role": role, "account": acct}


class ArenaRegisterIn(BaseModel):
    name: str
    model: str = ""
    capital: float = 1_000_000.0
    id: str | None = None


@app.post("/api/arena/agents")
def arena_register(body: ArenaRegisterIn, request: Request) -> dict[str, Any]:
    _require_mutation(request, None, account_scoped=False)
    try:
        acct = _account_store().create(
            body.name, body.capital, body.id or None,
            kind="agent", model=body.model, arena=True)
        key = _account_store().create_key(acct["id"], label="first")
        return {"account": acct, "api_key": key["api_key"]}
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/arena/leaderboard")
def arena_leaderboard(benchmark: str = "sh000300") -> dict[str, Any]:
    from ..trading.arena import leaderboard
    try:
        key = ("arena_lb", benchmark)
        return _cache.get(key, TTL_QUOTE,
                          lambda: leaderboard(benchmark, _account_store()))
    except Exception as e:
        raise _err(e)


@app.get("/api/arena/agents/{account_id}")
def arena_agent(account_id: str,
                benchmark: str = "sh000300") -> dict[str, Any]:
    from ..trading.arena import agent_detail
    try:
        return agent_detail(account_id, benchmark, _account_store())
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise _err(e)


@app.post("/api/arena/agents/{account_id}/keys")
def arena_new_key(account_id: str, request: Request) -> dict[str, Any]:
    _require_mutation(request, None, account_scoped=False)
    try:
        return _account_store().create_key(account_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/arena/agents/{account_id}/keys/revoke")
def arena_revoke(account_id: str, request: Request) -> dict[str, Any]:
    _require_mutation(request, None, account_scoped=False)
    if not _account_store().exists(account_id):
        raise HTTPException(status_code=404,
                            detail=f"unknown account {account_id!r}")
    return {"revoked": _account_store().revoke_keys(account_id)}


@app.get("/api/scheduler")
def scheduler_status() -> dict[str, Any]:
    from . import scheduler
    return scheduler.status()


@app.get("/api/market-clock")
def market_clock() -> dict[str, Any]:
    from . import scheduler
    from ..data.calendar import is_trading_day
    now = scheduler._now()
    return {"date": now.date().isoformat(),
            "server_time": now.isoformat(timespec="seconds"),
            "is_trading_day": is_trading_day(now.date())}


# ---------- backtest ----------

@app.post("/api/backtest")
def backtest(body: BacktestIn) -> dict[str, Any]:
    def run(strategy: str, params: dict[str, Any]) -> dict[str, Any]:
        return run_backtest(
            body.symbol, strategy, params, body.start, body.end,
            body.capital, "qfq", body.slippage_bps, body.min_trade_value)

    try:
        key = ("bt", body.symbol, body.strategy,
               tuple(sorted((body.params or {}).items())),
               body.start, body.end, body.capital,
               body.slippage_bps, body.min_trade_value)
        res = _cache.get(key, TTL_SLOW,
                         lambda: run(body.strategy, body.params))
        if body.strategy == "buy_hold":
            bench = res
        else:
            bench = _cache.get(
                ("bt", body.symbol, body.start, body.end, body.capital,
                 body.slippage_bps, "buy_hold"), TTL_SLOW,
                lambda: run("buy_hold", {}))
    except Exception as e:
        raise _err(e)
    return {**res, "benchmark": bench.get("equity_curve", [])}


@app.post("/api/backtest/portfolio")
def backtest_portfolio(body: PortfolioIn) -> dict[str, Any]:
    import json
    from ..backtest.portfolio import run_portfolio_backtest
    args = body.model_dump()
    key = ("bt_portfolio", json.dumps(args, sort_keys=True, default=str))
    try:
        return _cache.get(key, TTL_SLOW, lambda: run_portfolio_backtest(
            args["symbols"], args["weighting"], args["rebalance"],
            args["start"], args["end"], args["capital"],
            args["slippage_bps"], args["min_trade_value"],
            args["benchmark"]))
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@app.post("/api/backtest/scan")
def backtest_scan(body: ScanIn) -> dict[str, Any]:
    import json
    from ..backtest.engine import scan_backtest
    args = body.model_dump()
    key = ("bt_scan", json.dumps(args, sort_keys=True, default=str))
    try:
        return _cache.get(key, TTL_SLOW, lambda: scan_backtest(
            args["symbol"], args["strategy"], args["grid"],
            args["start"], args["end"], args["split"], args["metric"],
            args["capital"], args["slippage_bps"], args["min_trade_value"]))
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@app.post("/api/screen")
def screen_stocks(body: ScreenIn) -> dict[str, Any]:
    from ..research.screener import screen
    import json
    args = body.model_dump()
    key = ("screen", json.dumps(args, sort_keys=True, default=str))
    try:
        return _cache.get(key, TTL_INTRADAY,
                          lambda: screen(**args))
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@app.get("/api/peers/{symbol}")
def peers(symbol: str, limit: int = 30) -> dict[str, Any]:
    from ..research.peers import industry_peers
    try:
        return _cache.get(("peers", symbol, limit), 60.0,
                          lambda: industry_peers(symbol, limit))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise _err(e)


@app.get("/api/industries")
def industries() -> dict[str, Any]:
    from ..research.industry import list_industries
    return {"data": list_industries()}


@app.get("/api/strategies")
def strategies() -> dict[str, Any]:
    return {"data": list(STRATEGIES)}


# ---------- static frontend (SPA) ----------

def _resolve_dist() -> Path:
    env = os.environ.get("ASHARE_WEB_DIST", "").strip()
    if env:
        return Path(env)
    repo_dist = REPO_ROOT / "web" / "dist"
    if (repo_dist / "index.html").is_file():
        return repo_dist  # dev checkout: always use the freshest build
    pkg_static = Path(__file__).resolve().parent / "static"
    if (pkg_static / "index.html").is_file():
        return pkg_static  # installed wheel
    return repo_dist


_dist = _resolve_dist()
if _dist.is_dir():
    from fastapi.staticfiles import StaticFiles

    _index = _dist / "index.html"

    @app.get("/{full_path:path}")
    def spa(full_path: str):  # noqa: ANN202
        # /api/* routes are registered first and take priority; anything
        # else serves the file if it exists else index.html (SPA fallback).
        if full_path and not full_path.startswith("api"):
            candidate = _dist / full_path
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(_index)
