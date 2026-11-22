"""MCP server surface test — tools registered, no network."""
import asyncio

from ashare_mcp import server


def test_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    names = set(tools.keys()) if isinstance(tools, dict) else {
        t.name for t in tools}
    expected = {
        "search_stock", "get_quote", "get_quotes", "get_kline",
        "get_index_quote", "get_index_kline", "get_market_overview",
        "get_limit_pool", "get_money_flow",
        "get_earnings_calendar", "get_announcements", "get_factor_snapshot",
        "get_financial_abstract", "get_financial_statement",
        "paper_status", "paper_buy", "paper_sell", "paper_positions",
        "paper_orders", "paper_reset",
        "paper_add_trigger", "paper_triggers", "paper_cancel_trigger",
        "paper_check_triggers",
        "paper_list_accounts", "paper_create_account",
        "run_backtest", "provider_status",
        "screen_stocks", "list_industries",
    }
    assert expected <= names, f"missing: {expected - names}"
    assert len(names) == len(expected)  # 30 tools
