"""FastAPI backend for the ashare-mcp web frontend.

Serves /api/* JSON endpoints backed by the market-data facade, the paper
trading account and the backtest engine, plus the built SPA from web/dist
(with client-side-routing fallback to index.html).

Run: ``python -m ashare_mcp.web`` (uvicorn, default http://127.0.0.1:8600).
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..backtest.engine import STRATEGIES, run_backtest
from ..data.facade import market_data
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
TTL_SLOW = 600.0        # kline / financial / factor / statements


def _call(name: str, *args: Any, ttl: float = 0.0, **kwargs: Any) -> tuple[Any, str]:
    def load() -> tuple[Any, str]:
        return market_data.call(name, *args, **kwargs)
    if ttl <= 0:
        return load()
    return _cache.get((name, args, tuple(sorted(kwargs.items()))), ttl, load)


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


# ---------- paper account (lazy singleton, lock-guarded mutations) ----------

_acct_lock = threading.Lock()
_acct: PaperAccount | None = None


def _account() -> PaperAccount:
    global _acct
    if _acct is None:
        with _acct_lock:
            if _acct is None:
                _acct = PaperAccount()
    return _acct


def _mutate(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        with _acct_lock:
            return fn(*args, **kwargs)
    except Exception as e:
        raise _err(e)


class TradeIn(BaseModel):
    symbol: str
    shares: int


class TriggerIn(BaseModel):
    symbol: str
    side: str
    shares: int
    trigger_price: float
    condition: str = ">="
    note: str = ""


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


# ---------- app ----------

app = FastAPI(title="ashare-mcp web", version="0.1.0")


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
def paper_status() -> dict[str, Any]:
    return _mutate(_account().status)


@app.get("/api/paper/positions")
def paper_positions() -> dict[str, Any]:
    try:
        return {"data": _account().positions()}
    except Exception as e:
        raise _err(e)


@app.get("/api/paper/orders")
def paper_orders(limit: int = 50) -> dict[str, Any]:
    return {"data": _account().orders(limit)}


@app.get("/api/paper/triggers")
def paper_triggers() -> dict[str, Any]:
    return {"data": _account().triggers()}


@app.get("/api/paper/history")
def paper_history() -> dict[str, Any]:
    return {"data": _account().history()}


@app.post("/api/paper/buy")
def paper_buy(body: TradeIn) -> dict[str, Any]:
    return _mutate(_account().buy, body.symbol, body.shares)


@app.post("/api/paper/sell")
def paper_sell(body: TradeIn) -> dict[str, Any]:
    return _mutate(_account().sell, body.symbol, body.shares)


@app.post("/api/paper/triggers")
def paper_add_trigger(body: TriggerIn) -> dict[str, Any]:
    return _mutate(_account().add_trigger, body.symbol, body.side,
                   body.shares, body.trigger_price, body.condition, body.note)


@app.delete("/api/paper/triggers/{trigger_id}")
def paper_cancel_trigger(trigger_id: str) -> dict[str, Any]:
    return _mutate(_account().cancel_trigger, trigger_id)


@app.post("/api/paper/check")
def paper_check() -> dict[str, Any]:
    return _mutate(_account().check_triggers)


@app.post("/api/paper/reset")
def paper_reset(body: ResetIn) -> dict[str, Any]:
    return _mutate(_account().reset, body.capital)


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


@app.get("/api/strategies")
def strategies() -> dict[str, Any]:
    return {"data": list(STRATEGIES)}


# ---------- static frontend (SPA) ----------

_dist = Path(os.environ.get("ASHARE_WEB_DIST", REPO_ROOT / "web" / "dist"))
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
