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
| 模拟盘 | `paper_status` `paper_buy` `paper_sell` `paper_positions` `paper_orders` `paper_reset` | 1手=100股、T+1、±10/20/30/5%涨跌停、佣金万2.5+印花税万5+过户费万0.1，SQLite 多账户持久化 |
| 账户管理 | `paper_list_accounts` `paper_create_account` | 多模拟账户；所有 `paper_*` 工具均可加 `account` 参数（默认 `default`） |
| 条件单 | `paper_add_trigger` `paper_triggers` `paper_cancel_trigger` `paper_check_triggers` | 触发价买卖（突破/止损/低吸），查账户时自动评估成交 |
| 回测 | `run_backtest` `run_portfolio_backtest` `scan_backtest_params` | 单股策略+组合回测（等权/波动率倒数，W/M/Q调仓）+参数样本内外扫描，信号收盘产生、次日开盘成交 |
| 数据源 | `provider_status` | akshare 主源状态、tushare token 配置检查 |
| 选股 | `screen_stocks` `list_industries` | 全市场条件筛选（估值/市值/换手/动量/板块/行业），申万一级行业（2021版） |

共 **32 个工具**。

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

## Web 前端

主 UI：React + Vite + Tailwind + lightweight-charts，券商终端风格
（深色主题、红涨绿跌），后端是 `ashare_mcp.web` 里的 FastAPI
（`/api/*` + 静态托管构建产物）。

```powershell
# 一次性：安装 web 扩展并构建前端
uv pip install --python .venv\Scripts\python.exe -e ".[web]"
cd web; npm ci; npm run build; cd ..

# 运行（同时提供 /api 和前端页面）
.venv\Scripts\python.exe -m ashare_mcp.web     # http://127.0.0.1:8600
```

开发模式（前端热更新，`/api` 代理到 8600）：

```powershell
cd web; npm run dev   # http://127.0.0.1:5173
```

五个页面：首页（九大指数/自选股/账户摘要/市场广度）、个股
（专业K线+MA/MACD/RSI/BOLL+资金流+财务+因子+公告+快捷交易）、
模拟盘（净值曲线/持仓/订单/条件单/重置）、回测（策略vs买入持有+
交易标记）、市场（涨跌停池/业绩日历/全市场公告）。

环境变量：`ASHARE_WEB_HOST`（默认 127.0.0.1）、`ASHARE_WEB_PORT`
（默认 8600）、`ASHARE_WEB_DIST`（默认 `<repo>/web/dist`）。

## 本地数据存储 / Local storage

- `data/market.db` — **K线本地缓存（可随意删除）**。日K首次全量拉取后按结算点（A股 15:30 CST）增量同步；除权导致前/后复权基准变化时自动全量重抓；盘中未收盘的当日K只返回不落库。`ASHARE_MCP_STORE=0` 可完全禁用（直连网络）。
- `data/paper.db` — **模拟账户（多账户，非缓存）**。旧版 `data/paper_account.json` 首次启动自动迁移为 `default` 账户，原文件保留为 `paper_account.json.migrated`。
- **MCP**：所有 `paper_*` 工具接受 `account` 参数（默认 `"default"`）；`paper_list_accounts` / `paper_create_account` 管理账户。
- **Web 调度器**（uvicorn 内守护线程）：交易时段（9:30–11:30 / 13:00–15:00 CST）每分钟为有待触发条件单的账户跑 `check_triggers`；每日 15:35 后为所有账户落当日净值、并预热持仓/条件单个股与九大指数的 K线缓存。`ASHARE_WEB_SCHEDULER=0` 关闭；`GET /api/scheduler` 查状态。
- **`ashare-sync` CLI**：立即跑一次每日结算+缓存预热；`--force` 跳过节假日判断。
- **交易日历** `data/trade_calendar.json`：新浪交易日历（`calendar_trade_date_hist_sina`）本地缓存，7 天或越界自动刷新，取数失败回退旧文件；`GET /api/market-clock` 返回当前是否交易日，前端状态药丸节假日全天显示"休市"。
- **行业分类** `data/industry.json`：申万一级行业（31 个，2021版）代码→行业映射，7 天自动刷新（6 小时节流），取数失败回退旧文件与打包快照 `data/industry.csv`；`GET /api/industries`、`POST /api/screen`（网页"选股"页）使用。
- 已知限制：交易日历取数完全失败且无本地缓存时，盘中条件单检查退回到"周一~周五"规则——节假日盘中会用最近收盘价评估条件单（不会成交到不存在的行情）。

## Streamlit 看板（轻量旧版）

```powershell
.venv\Scripts\python.exe -m streamlit run app.py   # http://127.0.0.1:8501
```

四个页面：市场概览（指数/涨跌家数/涨停池/业绩日历）、个股行情
（K线+资金流+财务+因子快照+公告）、模拟盘（买卖/条件单/持仓/订单）、
策略回测（指标+净值曲线+交易明细）。保留为轻量备用 UI。

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
app.py                    # Streamlit 看板（轻量旧版）
web/                      # React+Vite 前端（npm run build -> web/dist）
scripts/build_page.py     # 生成 docs/index.html（GitHub Pages 快照页）
docs/index.html           # 静态展示页（每日自动刷新）
.github/workflows/        # refresh-page.yml 定时重建
src/ashare_mcp/
├── server.py             # FastMCP 入口，32 个工具
├── config.py             # env 配置、数据目录
├── utils.py              # 代码/日期归一化、重采样
├── data/                 # facade + akshare + tushare
├── trading/paper.py      # 模拟盘引擎（SQLite 多账户）
├── trading/accounts.py   # 账户存储（paper.db）
├── data/store.py         # K线本地缓存（market.db）
├── backtest/engine.py    # 日线回测器+参数扫描；portfolio.py 组合回测
└── web/                  # FastAPI 后端（/api + SPA 静态托管）
data/paper.db             # 模拟账户状态（gitignored）
data/market.db            # K线缓存（可随时删除）
```

## Disclaimer

仅供研究与模拟交易，不构成投资建议。数据来自新浪/东方财富/同花顺公开
接口，时效性与准确性以源站为准。
