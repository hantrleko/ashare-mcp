"""Generate docs/index.html for GitHub Pages with real baked-in snapshots.

Run:  .venv\\Scripts\\python.exe scripts\\build_page.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plotly.io import to_html

from ashare_mcp.backtest.engine import run_backtest
from ashare_mcp.data.facade import market_data

UP, DOWN = "#ef5350", "#26a69a"
INDEX_BOARD = [
    ("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指"),
    ("sh000300", "沪深300"), ("sh000688", "科创50"), ("bj899050", "北证50"),
]


def candle_fig(symbol: str) -> go.Figure:
    sd = (date.today() - timedelta(days=365)).strftime("%Y%m%d")
    bars, _ = market_data.call("get_kline", symbol, period="daily",
                               start_date=sd, end_date="", adjust="qfq")
    df = pd.DataFrame(bars).tail(180)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name=symbol,
        increasing_line_color=UP, decreasing_line_color=DOWN), row=1, col=1)
    for w, c in ((5, "#f0b90b"), (20, "#7b7ff2"), (60, "#aab2c0")):
        fig.add_trace(go.Scatter(x=df["date"], y=df["close"].rolling(w).mean(),
                                 line=dict(color=c, width=1), name=f"MA{w}"),
                      row=1, col=1)
    colors = [UP if c >= o else DOWN for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df["date"], y=df["volume"], marker_color=colors,
                         name="成交量"), row=2, col=1)
    fig.update_layout(height=480, showlegend=True,
                      xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#c9d1d9"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.01))
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], gridcolor="#21262d")
    fig.update_yaxes(gridcolor="#21262d")
    return fig


def equity_fig(symbol: str) -> tuple[go.Figure, dict]:
    r = run_backtest(symbol, "ma_cross", {"fast": 5, "slow": 20},
                     "20240101", date.today().strftime("%Y%m%d"),
                     1_000_000.0)
    curve = pd.DataFrame(r["equity_curve"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve["date"], y=curve["equity"], mode="lines",
                             line=dict(color="#7b7ff2", width=1.8), name="净值"))
    fig.add_hline(y=r["capital"], line_dash="dot", line_color="#555")
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#c9d1d9"), showlegend=False,
                      yaxis_title="资产")
    fig.update_xaxes(gridcolor="#21262d")
    fig.update_yaxes(gridcolor="#21262d")
    return fig, r


def index_cards() -> str:
    cards = []
    for sym, name in INDEX_BOARD:
        try:
            q, _ = market_data.call("get_index_quote", sym)
        except Exception:
            continue
        pct = q.get("pct_chg")
        color = UP if isinstance(pct, (int, float)) and pct >= 0 else DOWN
        pct_s = f"{float(pct):+.2f}%" if isinstance(pct, (int, float)) else "—"
        cards.append(
            f'<div class="idx"><span class="idx-name">{name}</span>'
            f'<span class="idx-price">{float(q.get("price") or 0):,.2f}</span>'
            f'<span class="idx-pct" style="color:{color}">{pct_s}</span></div>')
    return '<div class="idx-grid">' + "".join(cards) + "</div>"


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ashare-mcp · A股数据 / 模拟盘 / 回测 MCP 工具包</title>
<script src="https://cdn.plot.ly/plotly-3.1.1.min.js"></script>
<style>
:root{{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--sub:#8b949e;--accent:#7b7ff2;--up:{UP};--down:{DOWN}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:960px;margin:0 auto;padding:0 20px}}
header{{padding:64px 0 40px;text-align:center}}
h1{{font-size:2.4rem;margin:0 0 12px}}
h1 code{{color:var(--accent)}}
.tagline{{color:var(--sub);font-size:1.1rem;margin:0 0 24px}}
.badges img{{margin:0 4px}}
.btn{{display:inline-block;margin:6px 4px;padding:10px 22px;border-radius:8px;text-decoration:none;font-weight:600}}
.btn-p{{background:var(--accent);color:#fff}}
.btn-g{{border:1px solid var(--line);color:var(--fg)}}
section{{margin:44px 0}}
h2{{font-size:1.4rem;border-left:4px solid var(--accent);padding-left:12px;margin-bottom:18px}}
.feat{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}}
.feat div{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}}
.feat b{{display:block;margin-bottom:6px}}
.feat span{{color:var(--sub);font-size:.9rem}}
.idx-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.idx{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column}}
.idx-name{{color:var(--sub);font-size:.85rem}}
.idx-price{{font-size:1.25rem;font-weight:700;margin:2px 0}}
.idx-pct{{font-weight:600}}
.chart{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px}}
.chart h3{{margin:8px 10px;font-size:1rem;color:var(--sub);font-weight:500}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 14px}}
.metrics div{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px}}
.metrics b{{font-size:1.05rem}}
.metrics span{{color:var(--sub);font-size:.8rem;display:block}}
pre{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;overflow:auto;font-size:.85rem}}
code{{color:#ffa657}}
footer{{border-top:1px solid var(--line);margin-top:56px;padding:28px 0;color:var(--sub);font-size:.85rem;text-align:center}}
.note{{color:var(--sub);font-size:.85rem}}
</style>
</head>
<body>
<div class="wrap">
<header>
<h1><code>ashare-mcp</code></h1>
<p class="tagline">A股行情 · 模拟盘 · 策略回测 · 财务基本面 — 给 AI agent 用的 MCP 工具包<br>akshare 主源 / tushare 降级 · 19 个工具 · 真实交易规则</p>
<div class="badges">
<img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?logo=python&logoColor=white" alt="">
<img src="https://img.shields.io/badge/MCP-stdio-7b7ff2" alt="">
<img src="https://img.shields.io/badge/license-MIT-green" alt="">
</div>
<div style="margin-top:20px">
<a class="btn btn-p" href="https://github.com/hantrleko/ashare-mcp">GitHub 仓库</a>
<a class="btn btn-g" href="{DEMO_URL}">在线 Demo（本机隧道）</a>
</div>
<p class="note">快照数据生成于 {GEN_DATE}（静态页，非实时）</p>
</header>

<section>
<h2>指数快照</h2>
{IDX_CARDS}
</section>

<section>
<h2>功能</h2>
<div class="feat">
<div><b>行情数据</b><span>搜索/报价/K线/指数/涨跌家数/涨停池/主力资金流，新浪优先+东财降级</span></div>
<div><b>模拟盘</b><span>1手=100股、T+1、涨跌停校验、佣金+印花税+过户费</span></div>
<div><b>策略回测</b><span>均线交叉/动量/网格/买入持有，次日开盘成交无未来函数</span></div>
<div><b>财务基本面</b><span>财务指标摘要 + 利润表/资产负债表/现金流量表</span></div>
</div>
</section>

<section>
<h2>示例：个股 K 线</h2>
<div class="chart"><h3>贵州茅台 600519 · 近一年日K（前复权）</h3>{FIG_KLINE}</div>
</section>

<section>
<h2>示例：策略回测</h2>
<div class="metrics">
<div><b>{BT_RET}%</b><span>总收益</span></div>
<div><b>{BT_CAGR}%</b><span>年化</span></div>
<div><b>{BT_DD}%</b><span>最大回撤</span></div>
<div><b>{BT_SHARPE}</b><span>Sharpe</span></div>
<div><b>{BT_TRADES}笔 / {BT_WIN}%</b><span>交易 / 胜率</span></div>
</div>
<div class="chart"><h3>平安银行 000001 · 5/20均线交叉 · 2024-01-01 至今 · 初始100万</h3>{FIG_EQUITY}</div>
<p class="note">信号收盘产生、次日开盘成交；含佣金万2.5+印花税万5+过户费万0.1。</p>
</section>

<section>
<h2>接入你的 AI 客户端</h2>
<pre>{{<span style="color:#8b949e">// claude_desktop_config.json / .cursor/mcp.json</span>
"mcpServers": {{
  "ashare": {{
    "command": "uvx",
    "args": ["--from", "git+https://github.com/hantrleko/ashare-mcp", "ashare-mcp"]
  }}
}}}}</pre>
<p class="note">或本地跑：<code>pip install -e .</code> 后 <code>python -m ashare_mcp.server</code>。网页看板：<code>streamlit run app.py</code></p>
</section>

<footer>
<p>仅供研究与模拟，非投资建议 · 数据：新浪/东财/同花顺公开接口 · <a style="color:var(--accent)" href="https://github.com/hantrleko/ashare-mcp">github.com/hantrleko/ashare-mcp</a></p>
</footer>
</div>
</body>
</html>
"""


def main() -> None:
    demo_url = "https://modems-brick-mind-legs.trycloudflare.com"
    print("fetching index quotes…")
    idx = index_cards()
    print("fetching kline 600519…")
    fig_k = to_html(candle_fig("600519"), full_html=False,
                    include_plotlyjs=False)
    print("running backtest 000001…")
    fig_e, r = equity_fig("000001")
    fig_e_h = to_html(fig_e, full_html=False, include_plotlyjs=False)

    html = TEMPLATE.format(
        UP=UP, DOWN=DOWN,
        GEN_DATE=date.today().isoformat(),
        DEMO_URL=demo_url,
        IDX_CARDS=idx,
        FIG_KLINE=fig_k,
        FIG_EQUITY=fig_e_h,
        BT_RET=round(r["total_return"] * 100, 2),
        BT_CAGR=round(r["annual_return"] * 100, 2),
        BT_DD=round(r["max_drawdown"] * 100, 2),
        BT_SHARPE=r["sharpe"],
        BT_TRADES=r["num_trades"],
        BT_WIN=round((r["win_rate"] or 0) * 100, 0),
    )
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
