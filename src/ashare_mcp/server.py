"""MCP server entrypoint: A-share market data, paper trading, backtest, fundamentals."""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .backtest.engine import STRATEGIES, run_backtest
from .data.facade import market_data
from .trading.paper import PaperAccount

mcp = FastMCP("ashare-mcp")

_account: PaperAccount | None = None


def _acct() -> PaperAccount:
    global _account
    if _account is None:
        _account = PaperAccount()
    return _account


def _err(e: Exception) -> dict[str, Any]:
    return {"error": str(e)}


def _wrap(result: Any, source: str, **extra: Any) -> dict[str, Any]:
    return {"source": source, **extra, "data": result}


# ---------------- market data ----------------

@mcp.tool()
def search_stock(query: str, limit: int = 10) -> dict[str, Any]:
    """Search A-share stocks by code or name (e.g. "600519", "茅台", "平安").

    Returns up to `limit` matches with 6-digit code, name and market
    (sh/sz/bj). Use the returned code for other tools.
    """
    try:
        res, src = market_data.call("search_stock", query, limit)
        return {"source": src, "count": len(res), "results": res}
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_quote(symbol: str) -> dict[str, Any]:
    """Realtime snapshot quote for one A-share.

    `symbol` accepts "000001", "sz000001", "000001.SZ", "sh600000".
    Returns price, pct_chg, volume, amount, turnover, PE/PB, market cap.
    """
    try:
        res, src = market_data.call("get_quote", symbol)
        return _wrap(res, src)
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_quotes(symbols: list[str]) -> dict[str, Any]:
    """Batch realtime quotes for multiple symbols (comma list also OK)."""
    try:
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        res, src = market_data.call("get_quotes", list(symbols))
        return _wrap(res, src)
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_kline(symbol: str, period: str = "daily",
              start_date: str = "", end_date: str = "",
              adjust: str = "qfq", limit: int = 250) -> dict[str, Any]:
    """Historical OHLCV bars for a stock or ETF.

    - symbol: "000001" / "sz000001" / "000001.SZ" / "sh600000"
    - period: daily | weekly | monthly
    - adjust: "" (raw) | "qfq" (forward-adjusted, default) | "hfq"
    - dates: YYYYMMDD or YYYY-MM-DD; empty = default range
    - limit: max bars returned (default 250, keeps most recent)
    """
    try:
        res, src = market_data.call(
            "get_kline", symbol, period=period,
            start_date=start_date, end_date=end_date, adjust=adjust)
        n = max(1, min(int(limit), 2000))
        if len(res) > n:
            res = res[-n:]
        return {"source": src, "count": len(res), "bars": res}
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_index_quote(symbol: str = "sh000001") -> dict[str, Any]:
    """Realtime quote for a market index.

    symbol like "sh000001" (上证指数), "sz399001" (深证成指),
    "sz399006" (创业板指), "sh000300" (沪深300). Bare "000001" is
    interpreted as SH index — use get_kline for the stock 平安银行.
    """
    try:
        res, src = market_data.call("get_index_quote", symbol)
        return _wrap(res, src)
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_index_kline(symbol: str = "sh000001", period: str = "daily",
                    start_date: str = "", end_date: str = "",
                    limit: int = 500) -> dict[str, Any]:
    """Historical bars for a market index (e.g. sh000001, sz399006)."""
    try:
        res, src = market_data.call(
            "get_index_kline", symbol, period=period,
            start_date=start_date, end_date=end_date)
        n = max(1, min(int(limit), 3000))
        if len(res) > n:
            res = res[-n:]
        return {"source": src, "count": len(res), "bars": res}
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_market_overview() -> dict[str, Any]:
    """Major index quotes (上证/深成/创业板/沪深300/中证500/1000...) plus
    market breadth: advance/decline/flat counts, avg change, total turnover."""
    try:
        res, src = market_data.call("get_market_overview")
        return _wrap(res, src)
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_limit_pool(date_str: str = "", pool: str = "zt",
                   limit: int = 300) -> dict[str, Any]:
    """Limit-up/limit-down pools for a trading day.

    - date_str: YYYYMMDD or YYYY-MM-DD, empty = today
    - pool: "zt" 涨停 | "dt" 跌停 | "prev" 昨涨停今表现 | "strong" 强势股
      | "zb" 炸板 | "new" 次新股
    """
    try:
        res, src = market_data.call("get_limit_pool", date_str, pool, limit)
        return {"source": src, "pool": pool, "date": date_str or "today",
                "count": len(res), "items": res}
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_money_flow(symbol: str, days: int = 20) -> dict[str, Any]:
    """Main-force (主力) capital flow history for a stock.

    Returns daily main/extra-large/large/mid/small net inflow amounts
    and ratios for the last `days` trading days.
    """
    try:
        res, src = market_data.call("get_money_flow", symbol, days)
        return {"source": src, "symbol": symbol, "count": len(res),
                "items": res}
    except Exception as e:
        return _err(e)


# ---------------- fundamentals ----------------

@mcp.tool()
def get_financial_abstract(symbol: str, indicator: str = "按报告期",
                           limit: int = 12) -> dict[str, Any]:
    """Key financial indicators by report period (THS abstract).

    indicator: "按报告期" (default) | "按单季" | "按年度" | "累计报告期"
    Columns include 净利润, 营业总收入, 净资产收益率, 毛利率 etc.
    """
    try:
        res, src = market_data.call(
            "get_financial_abstract", symbol, indicator, limit)
        return {"source": src, "symbol": symbol, "count": len(res),
                "items": res}
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_financial_statement(symbol: str, statement: str = "income",
                            limit: int = 12) -> dict[str, Any]:
    """Financial statements: statement = income 利润表 | balance 资产负债表
    | cashflow 现金流量表. Returns recent periods (default 12)."""
    try:
        res, src = market_data.call(
            "get_financial_statement", symbol, statement, limit)
        return {"source": src, "symbol": symbol, "statement": statement,
                "count": len(res), "items": res}
    except Exception as e:
        return _err(e)


# ---------------- paper trading ----------------

@mcp.tool()
def paper_status() -> dict[str, Any]:
    """Paper account summary: cash, market value, equity, PnL, position count."""
    try:
        return _acct().status()
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_buy(symbol: str, shares: int, price: float | None = None) -> dict[str, Any]:
    """Buy shares in the paper account. Lots of 100; T+1; price limits
    enforced. price=None -> fill at latest quote. Fees included."""
    try:
        return _acct().buy(symbol, shares, price)
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_sell(symbol: str, shares: int, price: float | None = None) -> dict[str, Any]:
    """Sell shares in the paper account. Only T+1-available shares can be
    sold. Lots of 100 unless closing the whole position."""
    try:
        return _acct().sell(symbol, shares, price)
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_positions() -> dict[str, Any]:
    """All paper positions with last price, market value and unrealized PnL."""
    try:
        return {"positions": _acct().positions()}
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_orders(limit: int = 50) -> dict[str, Any]:
    """Recent paper-trading orders (newest first), with fees and realized PnL."""
    try:
        return {"orders": _acct().orders(limit)}
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_reset(capital: float = 1_000_000.0) -> dict[str, Any]:
    """Reset the paper account to a fresh state with given starting capital (CNY)."""
    try:
        return _acct().reset(capital)
    except Exception as e:
        return _err(e)


# ---------------- backtest ----------------

@mcp.tool()
def run_backtest(symbol: str, strategy: str = "ma_cross",
                 params: dict | None = None,
                 start_date: str = "", end_date: str = "",
                 capital: float = 1_000_000.0, adjust: str = "qfq",
                 slippage_bps: float = 0.0,
                 min_trade_value: float = 5000.0) -> dict[str, Any]:
    """Backtest a daily strategy on A-share kline data.

    strategy: "ma_cross" (params fast=5, slow=20) | "momentum"
      (lookback=20, threshold=0.03) | "grid" (grids=10, optional lower/upper)
      | "buy_hold" benchmark.
    Signals at close execute at next open; long-only; A-share fees applied.
    Trades below min_trade_value CNY are skipped (full exits always allowed).
    Returns metrics (total/annual return, max drawdown, Sharpe, win rate),
    downsampled equity curve and last 100 trades.
    """
    try:
        return run_backtest(symbol, strategy, params or {},
                            start_date, end_date, capital, adjust,
                            slippage_bps, min_trade_value)
    except Exception as e:
        return _err(e)


@mcp.tool()
def provider_status() -> dict[str, Any]:
    """Which data providers are configured (akshare primary, tushare fallback)."""
    try:
        return market_data.provider_status()
    except Exception as e:
        return _err(e)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
