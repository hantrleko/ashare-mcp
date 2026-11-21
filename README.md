# ashare-mcp

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776ab?logo=python&logoColor=white)](https://github.com/hantrleko/ashare-mcp)
[![MCP](https://img.shields.io/badge/MCP-stdio-7b7ff2)](https://modelcontextprotocol.io)
[![CI](https://github.com/hantrleko/ashare-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/hantrleko/ashare-mcp/actions)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Demo Page](https://img.shields.io/badge/demo-GitHub%20Pages-orange)](https://hantrleko.github.io/ashare-mcp/)

MCP server + Streamlit dashboard for **A-share (China mainland) market data,
paper trading, strategy backtesting and company fundamentals** — built for AI
agents (Claude Desktop, Cursor, Claude Code, …).

Data: **akshare** primary (Sina/Tencent endpoints preferred, East Money
fallback with rate-limit cooldown), **tushare** automatic fallback when
`TUSHARE_TOKEN` is set.

📊 **[在线展示页 / Live snapshot](https://hantrleko.github.io/ashare-mcp/)** —
每日收盘后 GitHub Actions 自动刷新。

---

## 功能总览

| 模块 | MCP 工具 | 说明 |
|---|---|---|
| 行情数据 | `search_stock` `get_quote` `get_quotes` `get_kline` `get_index_quote` `get_index_kline` `get_market_overview` `get_limit_pool` `get_money_flow` | 搜索/实时报价/日周月K/指数/涨跌家数/涨停跌停池/主力资金流 |
| 事件与因子 | `get_earnings_calendar` `get_announcements` `get_factor_snapshot` | 业绩报表/预告/快报、公告查询、动量/波动/Beta/均线位置因子快照 |
| 财务基本面 | `get_financial_abstract` `get_financial_statement` | 财务指标摘要 + 利润表/资产负债表/现金流量表 |
| 模拟盘 | `paper_status` `paper_buy` `paper_sell` `paper_positions` `paper_orders` `paper_reset` | 1手=100股、T+1、±10/20/30/5%涨跌停、佣金万2.5+印花税万5+过户费万0.1，JSON持久化 |
| 条件单 | `paper_add_trigger` `paper_triggers` `paper_cancel_trigger` `paper_check_triggers` | 触发价买卖（突破/止损/低吸），查账户时自动评估成交 |
| 策略回测 | `run_backtest` | `ma_cross`/`momentum`/`grid`/`buy_hold`，信号收盘产生、次日开盘成交，无未来函数 |
| 数据源 | `provider_status` | akshare 主源状态、tushare token 配置检查 |

共 **26 个工具**。

## 安装

需要 Python ≥ 3.10。

```powershell
git clone https://github.com/hantrleko/ashare-mcp
cd ashare-mcp
uv venv --python 3.12 .venv          # 或 python -m venv .venv
uv pip install --python .venv\Scripts\python.exe -e .
```

可选：复制 `.env.example` → `.env`，填入 `TUSHARE_TOKEN` 启用降级数据源
（token 在 https://tushare.pro 免费注册）。

## 接入 MCP 客户端

Claude Desktop / Cursor（`claude_desktop_config.json` / `.cursor/mcp.json`）：

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

免克隆直接用（PyPI）：

```json
{
  "mcpServers": {
    "ashare": {
      "command": "uvx",
      "args": ["ashare-mcp-server"]
    }
  }
}
```

或跑 git 上的最新版：

```json
{
  "mcpServers": {
    "ashare": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/hantrleko/ashare-mcp", "ashare-mcp-server"]
    }
  }
}
```

Claude Code：

```powershell
claude mcp add ashare -- F:\Hermes\ashare-mcp\.venv\Scripts\python.exe -m ashare_mcp.server
```

## Web 看板

```powershell
.venv\Scripts\python.exe -m streamlit run app.py   # http://127.0.0.1:8501
```

四个页面：市场概览（指数/涨跌家数/涨停池/业绩日历）、个股行情
（K线+资金流+财务+因子快照+公告）、模拟盘（买卖/条件单/持仓/订单）、
策略回测（指标+净值曲线+交易明细）。

## 给 agent 的任务示例

- "茅台最近一年的日K线" → `get_kline("600519", "daily", adjust="qfq")`
- "今天涨停的股票有哪些" → `get_limit_pool(pool="zt")`（近30个交易日）
- "帮我模拟买入 100 股平安银行" → `paper_buy("000001", 100)`
- "茅台跌到 1400 以下帮我买 100 股" → `paper_add_trigger("600519","buy",100,1400,"<=")`
- "今年三季报谁的营收增速最快" → `get_earnings_calendar("20250930","yjbb")`
- "茅台今天发了什么公告" → `get_announcements("600519")`
- "平安银行的动量和波动率因子" → `get_factor_snapshot("000001")`
- "用5/20均线在茅台回测2024年以来" → `run_backtest("600519", "ma_cross", {"fast":5,"slow":20}, "20240101")`
- "茅台的利润表和主要财务指标" → `get_financial_statement` + `get_financial_abstract`

## 注意事项

- **代码格式**：`"000001"` `"sz000001"` `"000001.SZ"` `"sh600000"` 都认；
  6位裸码自动识别市场（6→沪、0/3→深、4/8/92→北）。
- **指数 vs 股票**：`sh000001`=上证指数；裸 `"000001"`=平安银行。
- **报价降级链**：东财快照 → 新浪1分钟线 → 新浪全市场快照 → 日线收盘；
  响应里都标 `source`/`note`，兜底数据不是实时会注明。
- **K线**：新浪优先、东财 `stock_zh_a_hist_em` 兜底（含限流冷却）。
- **涨停池**：只覆盖最近约30个交易日（东财接口限制）。
- **模拟盘**：纯模拟，不下真实订单。T+1 通过日期滚动实现。
- **回测**：做多、lot取整、最小交易额死区跳过碎单（清仓除外）。

## 项目结构

```
app.py                    # Streamlit 看板
scripts/build_page.py     # 生成 docs/index.html（GitHub Pages 快照页）
docs/index.html           # 静态展示页（每日自动刷新）
.github/workflows/        # refresh-page.yml 定时重建
src/ashare_mcp/
├── server.py             # FastMCP 入口，19 个工具
├── config.py             # env 配置、数据目录
├── utils.py              # 代码/日期归一化、重采样
├── data/                 # facade + akshare + tushare
├── trading/paper.py      # 模拟盘引擎（JSON 状态）
└── backtest/engine.py    # 日线回测器
data/paper_account.json   # 模拟盘状态（gitignored）
```

## Disclaimer

仅供研究与模拟交易，不构成投资建议。数据来自新浪/东方财富/同花顺公开
接口，时效性与准确性以源站为准。
