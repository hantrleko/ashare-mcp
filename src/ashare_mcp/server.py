"""MCP server entrypoint: A-share market data, paper trading, backtest, fundamentals."""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .backtest.engine import STRATEGIES, run_backtest
from .data.facade import market_data
from .trading.accounts import AccountStore
from .trading.paper import PaperAccount

mcp = FastMCP("ashare-mcp")

_store_instance: AccountStore | None = None


def _store() -> AccountStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = AccountStore()
    return _store_instance

_accounts: dict[str, PaperAccount] = {}


def _acct(account: str = "default") -> PaperAccount:
    if account not in _accounts:
        _accounts[account] = PaperAccount(account)
    return _accounts[account]


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


@mcp.tool()
def get_earnings_calendar(report_date: str = "", kind: str = "yjbb",
                          limit: int = 300) -> dict[str, Any]:
    """Earnings calendar for a quarter-end report date.

    - report_date: quarter end YYYYMMDD (e.g. 20250930); empty = latest Q3
    - kind: "yjbb" 业绩报表(正式披露) | "yjyg" 业绩预告 | "yysj" 业绩快报
    Returns EPS, revenue/profit YoY growth, ROE, margin, industry, and the
    latest announcement date for every A-share that reported.
    Note: first call per period crawls ~30-60s; cached 24h.
    """
    try:
        res, src = market_data.call("get_earnings_calendar",
                                    report_date, kind, limit)
        return {"source": src, "kind": kind, "count": len(res), "items": res}
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_announcements(symbol: str = "", date_str: str = "",
                      limit: int = 100) -> dict[str, Any]:
    """Exchange announcements: a whole trading day, or filtered to one stock.

    - date_str: YYYYMMDD or YYYY-MM-DD, empty = today
    - symbol: optional 6-digit code to filter
    Returns title/type/publish time/url per announcement.
    """
    try:
        res, src = market_data.call("get_announcements",
                                    symbol, date_str, limit)
        return {"source": src, "count": len(res), "items": res}
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_factor_snapshot(symbol: str, days: int = 250) -> dict[str, Any]:
    """Factor snapshot from daily bars: 20/60/120d momentum returns,
    20d annualized volatility, MA5/20/60/120 distance, avg turnover &
    amplitude, and 120d beta vs CSI-300."""
    try:
        res, src = market_data.call("get_factor_snapshot", symbol, days)
        return _wrap(res, src)
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
def paper_status(account: str = "default") -> dict[str, Any]:
    """Paper account summary: cash, market value, equity, PnL, position count.
    account: paper account id; default 'default'.
"""
    try:
        return _acct(account).status()
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_buy(symbol: str, shares: int, price: float | None = None, account: str = "default") -> dict[str, Any]:
    """Buy shares in the paper account. Lots of 100; T+1; price limits
    enforced. price=None -> fill at latest quote. Fees included.
    account: paper account id; default 'default'.
"""
    try:
        return _acct(account).buy(symbol, shares, price)
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_sell(symbol: str, shares: int, price: float | None = None, account: str = "default") -> dict[str, Any]:
    """Sell shares in the paper account. Only T+1-available shares can be
    sold. Lots of 100 unless closing the whole position.
    account: paper account id; default 'default'.
"""
    try:
        return _acct(account).sell(symbol, shares, price)
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_positions(account: str = "default") -> dict[str, Any]:
    """All paper positions with last price, market value and unrealized PnL.
    account: paper account id; default 'default'.
"""
    try:
        return {"positions": _acct(account).positions()}
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_orders(limit: int = 50, account: str = "default") -> dict[str, Any]:
    """Recent paper-trading orders (newest first), with fees and realized PnL.
    account: paper account id; default 'default'.
"""
    try:
        return {"orders": _acct(account).orders(limit)}
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_reset(capital: float = 1_000_000.0, account: str = "default") -> dict[str, Any]:
    """Reset the paper account to a fresh state with given starting capital (CNY).
    account: paper account id; default 'default'.
"""
    try:
        return _acct(account).reset(capital)
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_add_trigger(symbol: str, side: str, shares: int,
                      trigger_price: float, condition: str = ">=",
                      note: str = "", account: str = "default") -> dict[str, Any]:
    """Add a conditional (trigger) order to the paper account.

    - side: "buy" | "sell"; shares in lots of 100
    - condition ">=" fires when price >= trigger_price (breakout/stop-gain);
      "<=" fires when price <= trigger_price (dip-buy/stop-loss)
    Triggers are evaluated whenever the account is queried
    (status/positions/check_triggers). Fills go through the normal
    buy/sell path — T+1, price limits and fees still apply.
    account: paper account id; default 'default'.
"""
    try:
        return _acct(account).add_trigger(symbol, side, shares,
                                   trigger_price, condition, note)
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_triggers(account: str = "default") -> dict[str, Any]:
    """List all conditional orders (newest first) with status:
    pending | filled | failed | cancelled.
    account: paper account id; default 'default'.
"""
    try:
        return {"triggers": _acct(account).triggers()}
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_cancel_trigger(trigger_id: str, account: str = "default") -> dict[str, Any]:
    """Cancel a pending conditional order by its id.
    account: paper account id; default 'default'.
"""
    try:
        return _acct(account).cancel_trigger(trigger_id)
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_check_triggers(account: str = "default") -> dict[str, Any]:
    """Evaluate all pending conditional orders against latest quotes now.
    Returns the full trigger list and remaining pending count.
    account: paper account id; default 'default'.
"""
    try:
        return _acct(account).check_triggers()
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_list_accounts() -> dict[str, Any]:
    """List all paper-trading accounts (id, name, cash, last equity)."""
    try:
        from .trading.accounts import AccountStore
        return {"accounts": _store().list()}
    except Exception as e:
        return _err(e)


@mcp.tool()
def paper_create_account(name: str, capital: float = 1_000_000.0,
                         account_id: str = "") -> dict[str, Any]:
    """Create a new paper-trading account. account_id optional
    (a-z0-9_- max 32); empty -> random 8-char id."""
    try:
        return _store().create(name, capital, account_id or None)
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
def run_portfolio_backtest(symbols: list[str], weighting: str = "equal",
                           rebalance: str = "M", start_date: str = "",
                           end_date: str = "", capital: float = 1_000_000.0,
                           slippage_bps: float = 0.0,
                           min_trade_value: float = 5000.0,
                           benchmark: str = "sh000300") -> dict[str, Any]:
    """Backtest a 2–50 stock portfolio.

    weighting: "equal" | "inverse_vol" (1/vol of last 60 daily returns).
    rebalance: "W"|"M"|"Q" — first trading day of each period, orders at
    open from weights computed on the previous close. Suspended symbols
    are valued at last close and skipped; limit-up/down opens block
    orders. Returns metrics vs benchmark (sh000300/sh000905/sh000001),
    excess annual return, turnover, per-symbol contribution, holdings
    and rebalance log.
    """
    try:
        from .backtest.portfolio import run_portfolio_backtest as _r
        return _r(symbols, weighting, rebalance, start_date, end_date,
                  capital, slippage_bps, min_trade_value, benchmark)
    except Exception as e:
        return _err(e)


@mcp.tool()
def scan_backtest_params(symbol: str, strategy: str,
                         grid: dict, start_date: str = "",
                         end_date: str = "", split: float = 0.7,
                         metric: str = "sharpe",
                         capital: float = 1_000_000.0,
                         slippage_bps: float = 0.0,
                         min_trade_value: float = 5000.0) -> dict[str, Any]:
    """In/out-of-sample grid scan of one strategy's params.

    strategy: "ma_cross" (fast,slow) | "momentum" (lookback,threshold)
      | "grid" (grids,calib). grid: {param: [values]} (<=100 combos).
    Splits the series at `split` (default 0.7), optimizes `metric`
    ("sharpe"|"total_return"|"annual_return"|"max_drawdown") in-sample,
    and reports the IS-best combo's out-of-sample metrics and rank.
    """
    try:
        from .backtest.engine import scan_backtest
        return scan_backtest(symbol, strategy, grid, start_date, end_date,
                             split, metric, capital, slippage_bps,
                             min_trade_value)
    except Exception as e:
        return _err(e)


@mcp.tool()
def provider_status() -> dict[str, Any]:
    """Which data providers are configured (akshare primary, tushare fallback)."""
    try:
        return market_data.provider_status()
    except Exception as e:
        return _err(e)


@mcp.tool()
def screen_stocks(ranges: dict[str, list] | None = None,
                  industries: list[str] | None = None,
                  boards: list[str] | None = None,
                  exclude_st: bool = True,
                  exclude_suspended: bool = True,
                  momentum: dict[str, list] | None = None,
                  sort_by: str = "mkt_cap",
                  desc: bool = True,
                  limit: int = 100) -> dict[str, Any]:
    """Screen A-shares on the realtime snapshot.

    ranges: {field: [min, max]} (either may be null) over price, pct_chg,
    turnover, pe_ttm, pb, roe_est, mkt_cap, float_mkt_cap, amount,
    volume_ratio, amplitude. boards: main|chinext|star|bse.
    momentum: {mom_20|mom_60: [min, max]} — computed on stage-1
    candidates only, capped at 200.
    Returns {total_universe, matched, rows, as_of, notes}.
    """
    try:
        from .research.screener import screen
        return screen(ranges=ranges, industries=industries, boards=boards,
                      exclude_st=exclude_st,
                      exclude_suspended=exclude_suspended,
                      momentum=momentum, sort_by=sort_by, desc=desc,
                      limit=limit)
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_industries() -> dict[str, Any]:
    """Sina industry classification: [{name, count}] by member count."""
    try:
        from .research.industry import list_industries as _li
        return {"industries": _li()}
    except Exception as e:
        return _err(e)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
