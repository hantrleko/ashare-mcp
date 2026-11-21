# ashare-mcp

MCP server for **A-share (China mainland) market data, paper trading,
strategy backtesting and company fundamentals** — built for AI agents
(Claude Desktop, Cursor, Claude Code, etc.).

Data: **akshare** primary (Sina/Tencent endpoints preferred, East Money
fallback), **tushare** automatic fallback when `TUSHARE_TOKEN` is set.

## Features

| Area | Tools |
|---|---|
| Market data | `search_stock`, `get_quote`, `get_quotes`, `get_kline`, `get_index_quote`, `get_index_kline`, `get_market_overview`, `get_limit_pool`, `get_money_flow` |
| Fundamentals | `get_financial_abstract`, `get_financial_statement` |
| Paper trading | `paper_status`, `paper_buy`, `paper_sell`, `paper_positions`, `paper_orders`, `paper_reset` |
| Backtest | `run_backtest` (`ma_cross`, `momentum`, `grid`, `buy_hold`) |
| Meta | `provider_status` |

Paper trading models real A-share rules: 100-share lots, T+1, ±10%/20%/30%/5%
price limits, commission + stamp tax + transfer fees. State persists to
`data/paper_account.json`.

## Setup

Requires Python ≥ 3.10 (developed on 3.12 via `uv`).

```powershell
cd F:\Hermes\ashare-mcp
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e .
```

Optional: copy `.env.example` to `.env` and set `TUSHARE_TOKEN` for the
fallback provider (get one at https://tushare.pro).

## Web dashboard (看效果)

A Streamlit UI wraps the same engines — market overview, stock detail
(K-line/资金流/财务), paper trading and backtests:

```powershell
cd F:\Hermes\ashare-mcp
.venv\Scripts\python.exe -m streamlit run app.py
# opens at http://127.0.0.1:8501
```

## Connect an MCP client

The server speaks MCP over stdio. Example for Claude Desktop / Cursor
(`claude_desktop_config.json` or `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "ashare": {
      "command": "F:\\Hermes\\ashare-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "ashare_mcp.server"]
    }
  }
}
```

Or after `pip install -e .`, the `ashare-mcp` console script works too:

```json
{ "command": "ashare-mcp", "args": [] }
```

Claude Code:

```powershell
claude mcp add ashare -- F:\Hermes\ashare-mcp\.venv\Scripts\python.exe -m ashare_mcp.server
```

## Usage examples (what an agent can do)

- "茅台最近一年的日K线" → `get_kline("600519", "daily", adjust="qfq")`
- "今天涨停的股票有哪些" → `get_limit_pool(pool="zt")` (last ~30 trading days only)
- "帮我模拟买入 100 股平安银行" → `paper_buy("000001", 100)`
- "用5/20日均线叉在贵州茅台上回测2020年以来" → `run_backtest("600519", "ma_cross", {"fast":5,"slow":20}, "2020-01-01")`
- "茅台的利润表和主要财务指标" → `get_financial_statement` + `get_financial_abstract`

## Notes & limitations

- **Symbol format**: `"000001"`, `"sz000001"`, `"000001.SZ"`, `"sh600000"` all OK.
  Bare 6-digit codes auto-detect market (6→SH, 0/3→SZ, 4/8/92→BJ).
- **Index vs stock**: `sh000001` = 上证指数; bare `"000001"` = 平安银行 (SZ stock).
  Use `get_index_kline`/`get_index_quote` for indices.
- **Realtime quotes** prefer East Money snapshot; on IP rate-limit it falls
  back to Sina snapshot (slower, fewer fields), then to last daily close.
- **K-lines** prefer Sina, fall back to East Money `stock_zh_a_hist_em`.
- **Limit pools** only cover the most recent ~30 trading days (EM limit).
- **Financial statements** come from Sina (利润表/资产负债表/现金流量表);
  abstract indicators from EM `stock_financial_analysis_indicator_em`.
- **Paper trading** is simulated only — no real orders. T+1 enforced via
  date rollover; fees: commission 0.025% (min ¥5), stamp tax 0.05% sell-side,
  transfer 0.001%.
- **Backtest** executes signals at next day's open (no look-ahead),
  long-only, lot-rounded, with the same fee model.

## Project layout

```
src/ashare_mcp/
├── server.py          # FastMCP entry, 19 tools
├── config.py          # env config, data dir
├── utils.py           # symbol/date normalization, resample
├── data/
│   ├── facade.py      # provider router (akshare → tushare)
│   ├── akshare_data.py
│   └── tushare_data.py
├── trading/paper.py   # paper account engine (JSON state)
└── backtest/engine.py # daily-bar backtester
data/                  # paper_account.json (gitignored)
```
