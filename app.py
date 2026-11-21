"""Streamlit web UI for ashare-mcp.

Pages: 市场概览 / 个股行情(含资金流+财务) / 模拟盘 / 策略回测.
Run:  .venv\\Scripts\\python.exe -m streamlit run app.py
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import os
import sys
from pathlib import Path

try:
    import ashare_mcp  # noqa: F401
except ModuleNotFoundError:  # run from repo root without installing
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from ashare_mcp.backtest.engine import STRATEGIES, run_backtest
from ashare_mcp.data.facade import market_data
from ashare_mcp.trading.paper import PaperAccount

try:  # Streamlit Cloud secrets -> env var for the data layer
    os.environ.setdefault("TUSHARE_TOKEN",
                          str(st.secrets.get("TUSHARE_TOKEN", "")))
except Exception:
    pass

st.set_page_config(page_title="A股研究台 · ashare-mcp",
                   page_icon="📈", layout="wide")

UP, DOWN = "#ef5350", "#26a69a"          # A股习惯: 红涨绿跌
INDEX_BOARD = [
    ("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指"),
    ("sh000300", "沪深300"), ("sh000688", "科创50"), ("sh000016", "上证50"),
    ("sh000905", "中证500"), ("sh000852", "中证1000"), ("bj899050", "北证50"),
]


# ---------- data helpers ----------

@st.cache_data(ttl=90, show_spinner=False)
def _call(name: str, *args: Any) -> Any:
    return market_data.call(name, *args)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _call_hist(name: str, *args: Any, **kwargs: Any) -> Any:
    return market_data.call(name, *args, **kwargs)


@st.cache_resource
def _account() -> PaperAccount:
    return PaperAccount()


def _pct(v: Any) -> str:
    return f"{float(v):+.2f}%" if isinstance(v, (int, float)) else "—"


def _yi(v: Any) -> str:
    try:
        return f"{float(v) / 1e8:.1f}亿"
    except (TypeError, ValueError):
        return "—"


def _err_box(e: Exception) -> None:
    st.error(f"数据获取失败：{e}")


def _candle(df: pd.DataFrame, name: str) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name=name,
        increasing_line_color=UP, decreasing_line_color=DOWN),
        row=1, col=1)
    for w, c in ((5, "#f0b90b"), (20, "#7b7ff2"), (60, "#aab2c0")):
        if len(df) >= w:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["close"].rolling(w).mean(),
                line=dict(color=c, width=1), name=f"MA{w}"), row=1, col=1)
    colors = [UP if c >= o else DOWN for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df["date"], y=df["volume"],
                         marker_color=colors, name="成交量"), row=2, col=1)
    fig.update_layout(height=560, showlegend=True, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02))
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], row=1, col=1)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], row=2, col=1)
    return fig


def _search_pick(key: str) -> str | None:
    """Search box -> selectbox; returns 6-digit code or None."""
    q = st.text_input("搜索股票（代码或名称）", key=key + "_q",
                      placeholder="如 600519 / 茅台 / 平安银行")
    if not q.strip():
        return None
    try:
        hits, _ = _call("search_stock", q.strip(), 10)
    except Exception as e:
        _err_box(e)
        return None
    if not hits:
        st.warning("没有匹配的股票")
        return None
    labels = {f"{h['code']}  {h['name']}  ({h['market']})": h["code"] for h in hits}
    pick = st.selectbox("匹配结果", list(labels), key=key + "_pick")
    return labels[pick]


# ---------- pages ----------

def page_overview() -> None:
    st.header("市场概览")
    cards: list[tuple[str, dict]] = []
    with st.spinner("加载指数行情…"):
        for sym, name in INDEX_BOARD:
            try:
                q, _ = _call("get_index_quote", sym)
                cards.append((name, q))
            except Exception:
                continue
    if not cards:
        st.warning("指数行情暂不可用")
    for row_start in range(0, len(cards), 3):
        cols = st.columns(3)
        for col, (name, q) in zip(cols, cards[row_start:row_start + 3]):
            pct = q.get("pct_chg")
            col.metric(name, f"{float(q.get('price') or 0):,.2f}",
                       _pct(pct), delta_color="inverse")

    st.divider()
    st.subheader("涨跌家数 / 成交额")
    st.caption("需要全市场快照（新浪约70页，首次加载1–2分钟）；东财可用时更快。")
    if st.button("加载市场广度"):
        with st.spinner("拉取全市场快照…"):
            try:
                ov, src = _call("get_market_overview")
            except Exception as e:
                _err_box(e)
                return
            b = ov.get("breadth", {})
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("上涨", b.get("advance", "—"))
            c2.metric("下跌", b.get("decline", "—"))
            c3.metric("平盘", b.get("flat", "—"))
            c4.metric("平均涨跌幅", _pct(b.get("avg_pct_chg")))
            c5.metric("两市成交额", f"{b.get('total_amount_yi', '—')}亿")
            st.caption(f"数据源: {src}")

    st.divider()
    st.subheader("业绩日历")
    st.caption("按报告期查全市场业绩披露（首次爬取30–60秒，缓存24小时）")
    c1, c2 = st.columns(2)
    rpt = c1.text_input("报告期（季末 YYYYMMDD，如 20250930）", "20250930")
    kind = c2.selectbox("类型", ["yjbb", "yjyg", "yysj"],
                        format_func=lambda k: {"yjbb": "业绩报表", "yjyg": "业绩预告",
                                               "yysj": "业绩快报"}[k])
    if st.button("加载业绩数据", key="earn_btn"):
        with st.spinner("爬取全市场业绩数据…"):
            try:
                items, src = _call("get_earnings_calendar", rpt.strip(),
                                   kind, 500)
                st.caption(f"{len(items)} 条 · 数据源 {src}")
                st.dataframe(pd.DataFrame(items), use_container_width=True,
                             height=420)
            except Exception as e:
                _err_box(e)

    st.divider()
    st.subheader("涨跌停池")
    pool_map = {"涨停": "zt", "跌停": "dt", "炸板": "zb", "强势股": "strong",
                "昨涨停今表现": "prev", "次新股": "new"}
    c1, c2 = st.columns([1, 2])
    pool_cn = c1.selectbox("池子", list(pool_map))
    day = c2.text_input("交易日（YYYYMMDD，留空=今天）", "")
    if st.button("查询", key="pool_btn"):
        with st.spinner("查询中…"):
            try:
                items, src = _call("get_limit_pool", day.strip(), pool_map[pool_cn], 200)
                st.caption(f"{len(items)} 条 · 数据源 {src}（该接口只覆盖近30个交易日）")
                st.dataframe(pd.DataFrame(items), use_container_width=True,
                             height=420)
            except Exception as e:
                _err_box(e)


def page_stock() -> None:
    st.header("个股行情")
    code = _search_pick("stock")
    if not code:
        return

    try:
        quote, qsrc = _call("get_quote", code)
    except Exception as e:
        _err_box(e)
        return

    pct = quote.get("pct_chg")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric(quote.get("name") or code, f"{float(quote.get('price') or 0):.2f}",
              _pct(pct), delta_color="inverse")
    m2.metric("今开", quote.get("open", "—"))
    m3.metric("最高/最低",
              f"{quote.get('high', '—')} / {quote.get('low', '—')}")
    m4.metric("成交额", _yi(quote.get("amount")))
    m5.metric("换手率", _pct(quote.get("turnover")).replace("+", ""))
    m6.metric("PE/PB", f"{quote.get('pe_ttm', '—')} / {quote.get('pb', '—')}")
    cap = f"数据源 {qsrc}"
    if quote.get("note"):
        cap += f" · {quote['note']}"
    if quote.get("date"):
        cap += f" · {quote['date']}"
    st.caption(cap)

    tab_k, tab_flow, tab_fin, tab_stmt, tab_factor, tab_ann = st.tabs(
        ["K线", "资金流向", "财务指标", "三大报表", "因子快照", "公告"])

    with tab_k:
        c1, c2, c3 = st.columns(3)
        period = c1.selectbox("周期", ["daily", "weekly", "monthly"],
                              format_func=lambda p: {"daily": "日线", "weekly": "周线",
                                                     "monthly": "月线"}[p])
        adj = c2.selectbox("复权", ["qfq", "hfq", ""],
                           format_func=lambda a: {"qfq": "前复权", "hfq": "后复权",
                                                  "": "不复权"}[a])
        rng = c3.selectbox("区间", ["近1年", "近3年", "近5年", "全部"])
        years = {"近1年": 1, "近3年": 3, "近5年": 5}.get(rng)
        sd = "" if years is None else (
            date.today() - timedelta(days=365 * years)).strftime("%Y%m%d")
        with st.spinner("加载K线…"):
            try:
                bars, ksrc = _call_hist("get_kline", code, period=period,
                                        start_date=sd, end_date="", adjust=adj)
            except Exception as e:
                _err_box(e)
                bars = []
        if bars:
            df = pd.DataFrame(bars)
            st.plotly_chart(_candle(df, code), use_container_width=True)
            st.caption(f"{len(df)} 根K线 · 数据源 {ksrc}")

    with tab_flow:
        if st.button("加载主力资金流", key="flow_btn"):
            with st.spinner("加载中…"):
                try:
                    items, src = _call("get_money_flow", code, 30)
                    st.caption(f"数据源 {src}")
                    st.dataframe(pd.DataFrame(items), use_container_width=True)
                except Exception as e:
                    _err_box(e)

    with tab_fin:
        ind = st.selectbox("口径", ["按报告期", "按年度", "按单季", "累计报告期"])
        with st.spinner("加载财务指标…"):
            try:
                items, src = _call_hist("get_financial_abstract", code, ind, 12)
                st.caption(f"数据源 {src}")
                st.dataframe(pd.DataFrame(items), use_container_width=True)
            except Exception as e:
                _err_box(e)

    with tab_stmt:
        st_map = {"利润表": "income", "资产负债表": "balance",
                  "现金流量表": "cashflow"}
        stmt = st.selectbox("报表", list(st_map))
        with st.spinner("加载报表…"):
            try:
                items, src = _call_hist("get_financial_statement", code,
                                        st_map[stmt], 8)
                st.caption(f"数据源 {src}")
                st.dataframe(pd.DataFrame(items), use_container_width=True)
            except Exception as e:
                _err_box(e)

    with tab_factor:
        with st.spinner("计算因子…"):
            try:
                fac, fsrc = _call_hist("get_factor_snapshot", code, 250)
            except Exception as e:
                _err_box(e)
                fac = None
        if fac:
            fm = st.columns(5)
            fm[0].metric("20日收益", _pct(fac.get("ret_20d") and fac["ret_20d"] * 100).replace("+", "") if fac.get("ret_20d") is not None else "—")
            fm[1].metric("60日收益", f"{fac['ret_60d'] * 100:+.2f}%" if fac.get("ret_60d") is not None else "—")
            fm[2].metric("120日收益", f"{fac['ret_120d'] * 100:+.2f}%" if fac.get("ret_120d") is not None else "—")
            fm[3].metric("年化波动(20d)", f"{fac['vol_20d_ann'] * 100:.1f}%" if fac.get("vol_20d_ann") is not None else "—")
            fm[4].metric("Beta(120d vs沪深300)", fac.get("beta_120d", "—"))
            fm2 = st.columns(5)
            for col, k in zip(fm2, ("ma5", "ma20", "ma60", "ma120")):
                if fac.get(f"vs_{k}_pct") is not None:
                    col.metric(f"vs {k.upper()}", f"{fac[f'vs_{k}_pct']:+.2f}%")
            if fac.get("avg_turnover_20d") is not None:
                fm2[4].metric("20日平均换手", f"{fac['avg_turnover_20d']:.2f}%")
            st.caption(f"数据源 {fsrc} · {fac.get('bars')} 根K线")

    with tab_ann:
        ann_day = st.text_input("日期（YYYYMMDD，留空=今天）", "", key="ann_day")
        if st.button("查询公告", key="ann_btn"):
            with st.spinner("查询公告…"):
                try:
                    items, src = _call("get_announcements", code,
                                       ann_day.strip(), 50)
                    st.caption(f"{len(items)} 条 · 数据源 {src}")
                    st.dataframe(pd.DataFrame(items), use_container_width=True)
                except Exception as e:
                    _err_box(e)


def page_paper() -> None:
    st.header("模拟盘")
    st.caption("A股规则：1手=100股 · T+1 · ±10/20/30/5% 涨跌停校验 · "
               "佣金万2.5(最低5元)+印花税万5(卖出)+过户费万0.1")
    acct = _account()

    c1, c2 = st.columns(2)
    with c1.form("buy_form"):
        st.subheader("买入")
        b_sym = st.text_input("代码", "", placeholder="600519 / sz000001")
        b_shares = st.number_input("股数（100的倍数）", min_value=100,
                                   value=100, step=100)
        if st.form_submit_button("买入"):
            try:
                r = acct.buy(b_sym.strip(), int(b_shares))
                st.success(f"已成交 {r['code']} {r['shares']}股 @ {r['price']}"
                           f" · 金额{r['amount']} 费用{r['fee']}"
                           f" · 剩余现金{r['cash']}")
            except Exception as e:
                st.error(f"买入失败：{e}")
    with c2.form("sell_form"):
        st.subheader("卖出")
        s_sym = st.text_input("代码 ", "", placeholder="600519")
        s_shares = st.number_input("股数 ", min_value=100, value=100, step=100)
        if st.form_submit_button("卖出"):
            try:
                r = acct.sell(s_sym.strip(), int(s_shares))
                st.success(f"已成交 {r['code']} {r['shares']}股 @ {r['price']}"
                           f" · 盈亏{r.get('realized_pnl')}"
                           f" · 现金{r['cash']}")
            except Exception as e:
                st.error(f"卖出失败：{e}")

    st.divider()
    with st.spinner("刷新账户…"):
        stt = acct.status()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("总资产", f"{stt['equity']:,.0f}",
              f"{stt['total_return_pct']:+.2f}%" if stt.get("total_return_pct") is not None else None,
              delta_color="inverse")
    m2.metric("现金", f"{stt['cash']:,.0f}")
    m3.metric("持仓市值", f"{stt['market_value']:,.0f}")
    m4.metric("总盈亏", f"{stt['total_pnl']:+,.0f}")
    m5.metric("持仓数", stt["position_count"])

    st.subheader("条件单")
    with st.form("trigger_form"):
        t1, t2, t3, t4, t5 = st.columns(5)
        t_sym = t1.text_input("代码 ", "", placeholder="600519")
        t_side = t2.selectbox("方向", ["buy", "sell"],
                              format_func=lambda s: "买入" if s == "buy" else "卖出")
        t_shares = t3.number_input("股数  ", min_value=100, value=100, step=100)
        t_cond = t4.selectbox("条件", [">=", "<="],
                              format_func=lambda c: "价格 ≥ 触发价" if c == ">=" else "价格 ≤ 触发价")
        t_price = t5.number_input("触发价", min_value=0.01, value=10.0, step=0.01)
        if st.form_submit_button("添加条件单"):
            try:
                tr = acct.add_trigger(t_sym.strip(), t_side, int(t_shares),
                                      float(t_price), t_cond)
                st.success(f"已添加 #{tr['id']}：{tr['symbol']} {t_side} "
                           f"{tr['shares']}股 @ {t_cond} {tr['trigger_price']}")
            except Exception as e:
                st.error(f"添加失败：{e}")
    col_t1, col_t2 = st.columns([1, 4])
    if col_t1.button("立即评估触发", key="check_trg"):
        with st.spinner("检查行情…"):
            res = acct.check_triggers()
            st.caption(f"待触发 {res['pending']} 个")
    trg_id = col_t2.text_input("取消条件单（输入id）", "", placeholder="id")
    if col_t2.button("取消", key="cancel_trg") and trg_id.strip():
        try:
            acct.cancel_trigger(trg_id.strip())
            st.success(f"已取消 {trg_id.strip()}")
        except Exception as e:
            st.error(f"取消失败：{e}")
    trigs = acct.triggers()
    if trigs:
        st.dataframe(pd.DataFrame(trigs), use_container_width=True)
    else:
        st.info("暂无条件单（查看持仓/资产时会自动评估触发）")

    st.subheader("持仓")
    pos = acct.positions()
    if pos:
        st.dataframe(pd.DataFrame(pos), use_container_width=True)
    else:
        st.info("暂无持仓")

    st.subheader("订单")
    orders = acct.orders(50)
    if orders:
        st.dataframe(pd.DataFrame(orders), use_container_width=True)
    else:
        st.info("暂无订单")

    with st.expander("重置账户"):
        cap = st.number_input("初始资金", min_value=10_000.0,
                              value=1_000_000.0, step=100_000.0)
        if st.button("确认重置（清空持仓与订单）"):
            acct.reset(cap)
            st.success(f"账户已重置为 ¥{cap:,.0f}")
            st.rerun()


def page_backtest() -> None:
    st.header("策略回测")
    st.caption("信号在收盘产生、次日开盘成交（无未来函数）· 做多 · 含真实费用 · "
               "低于最小交易额的交易跳过（清仓除外）")

    param_widgets: dict[str, dict[str, tuple]] = {
        "ma_cross": {"fast": ("快线周期", 5), "slow": ("慢线周期", 20)},
        "momentum": {"lookback": ("回望天数", 20), "threshold": ("动量阈值", 0.03)},
        "grid": {"grids": ("网格数", 10), "lower": ("下沿(可空)", 0.0),
                 "upper": ("上沿(可空)", 0.0)},
        "buy_hold": {},
    }
    desc = {"ma_cross": "均线交叉：快线上穿慢线持有",
            "momentum": "动量：N日涨幅超过阈值持有",
            "grid": "网格：价格区间分档，低位满仓高位空仓",
            "buy_hold": "基准：全程持有"}

    with st.form("bt_form"):
        c1, c2, c3 = st.columns(3)
        symbol = c1.text_input("代码", "000001")
        strategy = c2.selectbox("策略", STRATEGIES,
                                format_func=lambda s: f"{s} — {desc[s]}")
        capital = c3.number_input("初始资金", min_value=10_000.0,
                                  value=1_000_000.0, step=100_000.0)
        c4, c5, c6 = st.columns(3)
        sd = c4.text_input("开始日期", "20240101")
        ed = c5.text_input("结束日期", date.today().strftime("%Y%m%d"))
        slip = c6.number_input("滑点(bps)", min_value=0.0, value=0.0, step=1.0)
        pcols = st.columns(4)
        params: dict[str, Any] = {}
        for (col, (pname, (label, default))) in zip(
                pcols, param_widgets[strategy].items()):
            v = col.text_input(label, str(default))
            try:
                params[pname] = float(v) if "." in str(v) else int(v)
                if pname in ("lower", "upper") and params[pname] == 0.0:
                    params[pname] = None
            except ValueError:
                params[pname] = None
        mtv = st.number_input("最小交易额(元)", min_value=0.0,
                              value=5000.0, step=1000.0)
        submitted = st.form_submit_button("运行回测")

    if not submitted:
        return
    with st.spinner("回测中（首次拉K线需几秒）…"):
        try:
            r = run_backtest(symbol.strip(), strategy, params,
                             sd.strip(), ed.strip(), float(capital),
                             "qfq", float(slip), float(mtv))
        except Exception as e:
            st.error(f"回测失败：{e}")
            return

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("期末资产", f"{r['final_equity']:,.0f}")
    m2.metric("总收益", f"{r['total_return'] * 100:+.2f}%")
    m3.metric("年化", f"{r['annual_return'] * 100:+.2f}%")
    m4.metric("最大回撤", f"{r['max_drawdown'] * 100:.2f}%")
    m5.metric("Sharpe", f"{r['sharpe']:.2f}")
    m6.metric("交易/胜率",
              f"{r['num_trades']}笔 / "
              + (f"{r['win_rate'] * 100:.0f}%" if r["win_rate"] is not None else "—"))
    st.caption(f"{r['symbol']} · {r['start']}–{r['end']} · {r['bars']}根K线 · "
               f"数据源 {r['source']}")

    curve = pd.DataFrame(r["equity_curve"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve["date"], y=curve["equity"],
                             mode="lines", line=dict(color="#7b7ff2", width=1.5),
                             name="净值"))
    fig.add_hline(y=r["capital"], line_dash="dot", line_color="#888")
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="资产", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    if r["trades"]:
        with st.expander(f"交易明细（最近{len(r['trades'])}笔）"):
            st.dataframe(pd.DataFrame(r["trades"]), use_container_width=True)


# ---------- shell ----------

PAGES = {
    "市场概览": page_overview,
    "个股行情": page_stock,
    "模拟盘": page_paper,
    "策略回测": page_backtest,
}

st.sidebar.title("📈 A股研究台")
page = st.sidebar.radio("页面", list(PAGES))
st.sidebar.divider()
try:
    ps = market_data.provider_status()
    st.sidebar.caption(
        f"数据源: {ps['primary']}（主） / {ps['fallback']}（备"
        f"{'·已配token' if ps['tushare_token_set'] else '·未配token'}）")
except Exception:
    pass
st.sidebar.caption("仅供研究与模拟，非投资建议。数据：新浪/东财/同花顺公开接口。")
PAGES[page]()
