import { useEffect, useState } from "react";
import { CandlestickSeries, LineSeries, createSeriesMarkers } from "lightweight-charts";
import { api, type BacktestResult, type Bar } from "../api";
import { Card, ErrorBanner, useChart } from "../components/ui";
import { SearchBox } from "../components/SearchBox";
import { DOWN, UP, fmtNum, fmtPct, fmtPrice, fmtSigned, todayYmd } from "../format";

const STRAT: Record<string, { label: string; desc: string; params: [string, string, number][] }> = {
  ma_cross: { label: "均线交叉", desc: "快线上穿慢线持有", params: [["fast", "快线周期", 5], ["slow", "慢线周期", 20]] },
  momentum: { label: "动量", desc: "N日涨幅超过阈值持有", params: [["lookback", "回望天数", 20], ["threshold", "动量阈值", 0.03]] },
  grid: { label: "网格", desc: "价格区间分档，低位满仓高位空仓", params: [["grids", "网格数", 10], ["lower", "下沿(0=自动)", 0], ["upper", "上沿(0=自动)", 0]] },
  buy_hold: { label: "买入持有", desc: "基准：全程持有", params: [] },
};

export default function Backtest() {
  const [symbol, setSymbol] = useState("000001");
  const [strategy, setStrategy] = useState("ma_cross");
  const [params, setParams] = useState<Record<string, string>>({ fast: "5", slow: "20" });
  const [start, setStart] = useState("20240101");
  const [end, setEnd] = useState(todayYmd());
  const [capital, setCapital] = useState(1_000_000);
  const [slip, setSlip] = useState(0);
  const [mtv, setMtv] = useState(5000);
  const [res, setRes] = useState<BacktestResult | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      const p: Record<string, number | null> = {};
      for (const [k] of STRAT[strategy].params) {
        const v = Number(params[k]);
        p[k] = Number.isFinite(v) && v !== 0 ? v : null;
      }
      const [bt, kl] = await Promise.all([
        api.backtest({
          symbol, strategy, params: p, start, end,
          capital, slippage_bps: slip, min_trade_value: mtv,
        }),
        api.kline(symbol, "daily", start, end, "qfq").catch(() => ({ data: [] as Bar[] })),
      ]);
      setRes(bt);
      setBars(kl.data);
    } catch (e) { setErr(e); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        信号在收盘产生、次日开盘成交（无未来函数）· 做多 · 含真实费用 · 低于最小交易额的交易跳过（清仓除外）
      </p>
      <Card title="回测参数">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <div>
            <label className="mb-1 block text-xs text-slate-500">代码</label>
            <div className="flex gap-1">
              <input value={symbol} onChange={(e) => setSymbol(e.target.value)}
                className="num w-full rounded border border-line bg-panel2 px-2 py-1.5 text-sm outline-none" />
            </div>
            <SearchBox className="mt-1" onPick={(h) => setSymbol(h.code)} />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">策略</label>
            <select value={strategy} onChange={(e) => {
              const s = e.target.value;
              setStrategy(s);
              const p: Record<string, string> = {};
              for (const [k, , d] of STRAT[s].params) p[k] = String(d);
              setParams(p);
            }} className="w-full rounded border border-line bg-panel2 px-2 py-1.5 text-sm">
              {Object.entries(STRAT).map(([k, v]) => (
                <option key={k} value={k}>{v.label} — {v.desc}</option>
              ))}
            </select>
          </div>
          {STRAT[strategy].params.map(([k, label]) => (
            <div key={k}>
              <label className="mb-1 block text-xs text-slate-500">{label}</label>
              <input value={params[k] ?? ""} onChange={(e) => setParams({ ...params, [k]: e.target.value })}
                className="num w-full rounded border border-line bg-panel2 px-2 py-1.5 text-sm outline-none" />
            </div>
          ))}
          <Field label="开始日期"><input value={start} onChange={(e) => setStart(e.target.value)} className={inp} /></Field>
          <Field label="结束日期"><input value={end} onChange={(e) => setEnd(e.target.value)} className={inp} /></Field>
          <Field label="初始资金"><input type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} className={inp} /></Field>
          <Field label="滑点(bps)"><input type="number" value={slip} onChange={(e) => setSlip(Number(e.target.value))} className={inp} /></Field>
          <Field label="最小交易额"><input type="number" value={mtv} onChange={(e) => setMtv(Number(e.target.value))} className={inp} /></Field>
          <div className="flex items-end">
            <button onClick={run} disabled={busy}
              className="w-full rounded bg-up/90 py-1.5 text-sm font-medium text-white hover:bg-up disabled:opacity-40">
              {busy ? "回测中…" : "运行回测"}
            </button>
          </div>
        </div>
      </Card>
      <ErrorBanner error={err} />

      {res && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-6">
            <M label="期末资产" v={fmtNum(res.final_equity)} />
            <M label="总收益" v={fmtPct(res.total_return * 100)} cls={res.total_return >= 0 ? "text-up" : "text-down"} />
            <M label="年化" v={fmtPct(res.annual_return * 100)} cls={res.annual_return >= 0 ? "text-up" : "text-down"} />
            <M label="最大回撤" v={fmtPct(res.max_drawdown * 100)} cls="text-down" />
            <M label="Sharpe" v={res.sharpe.toFixed(2)} />
            <M label="交易/胜率" v={`${res.num_trades}笔 / ${res.win_rate != null ? (res.win_rate * 100).toFixed(0) + "%" : "—"}`} />
          </div>
          <p className="text-xs text-slate-500">
            {res.symbol} · {res.start}–{res.end} · {res.bars}根K线 · 数据源 {res.source ?? "—"}
          </p>

          <Card title="净值 vs 买入持有">
            <EquityVsBench res={res} />
          </Card>

          <Card title="价格与交易点">
            <PriceWithTrades bars={bars} res={res} />
          </Card>

          {res.trades.length > 0 && (
            <Card title={`交易明细（最近${res.trades.length}笔）`}>
              <div className="max-h-80 overflow-x-auto">
                <table className="w-full whitespace-nowrap text-xs">
                  <thead>
                    <tr className="border-b border-line text-left text-slate-500">
                      {["日期", "方向", "价格", "股数", "金额", "费用", "盈亏"].map((h) => (
                        <th key={h} className="px-2 py-1.5 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...res.trades].reverse().map((t, i) => (
                      <tr key={i} className="border-b border-line/40">
                        <td className="num px-2 py-1.5 text-slate-400">{t.date}</td>
                        <td className={`px-2 py-1.5 ${t.side === "buy" ? "text-up" : "text-down"}`}>
                          {t.side === "buy" ? "买入" : "卖出"}
                        </td>
                        <td className="num px-2 py-1.5">{fmtPrice(t.price)}</td>
                        <td className="num px-2 py-1.5">{t.shares}</td>
                        <td className="num px-2 py-1.5">{fmtNum(t.amount)}</td>
                        <td className="num px-2 py-1.5">{t.fee.toFixed(2)}</td>
                        <td className={`num px-2 py-1.5 ${t.pnl != null ? (t.pnl >= 0 ? "text-up" : "text-down") : ""}`}>
                          {t.pnl != null ? fmtSigned(t.pnl) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

const inp = "num w-full rounded border border-line bg-panel2 px-2 py-1.5 text-sm outline-none";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs text-slate-500">{label}</label>
      {children}
    </div>
  );
}

function M({ label, v, cls = "" }: { label: string; v: string; cls?: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`num text-base font-medium ${cls}`}>{v}</div>
    </div>
  );
}

function EquityVsBench({ res }: { res: BacktestResult }) {
  const { ref, chart } = useChart({ height: 320 });
  useEffect(() => {
    if (!chart) return;
    const s1 = chart.addSeries(LineSeries, { color: "#7b7ff2", lineWidth: 2, title: "策略" });
    s1.setData(res.equity_curve.map((p) => ({ time: p.date, value: p.equity })));
    const s2 = chart.addSeries(LineSeries, { color: "#8b93a7", lineWidth: 1, lineStyle: 2, title: "买入持有" });
    s2.setData(res.benchmark.map((p) => ({ time: p.date, value: p.equity })));
    chart.timeScale().fitContent();
  }, [chart, res]);
  return (
    <div>
      <div className="mb-1 flex gap-4 text-xs text-slate-400">
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-[#7b7ff2] align-middle" />策略</span>
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-[#8b93a7] align-middle" />买入持有</span>
      </div>
      <div ref={ref} className="w-full" />
    </div>
  );
}

function PriceWithTrades({ bars, res }: { bars: Bar[]; res: BacktestResult }) {
  const { ref, chart } = useChart({ height: 320 });
  useEffect(() => {
    if (!chart || !bars.length) return;
    const s = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN,
      wickUpColor: UP, wickDownColor: DOWN,
    });
    s.setData(bars.map((b) => ({ time: b.date, open: b.open, high: b.high, low: b.low, close: b.close })));
    const markers = res.trades.map((t) => ({
      time: t.date,
      position: t.side === "buy" ? "belowBar" as const : "aboveBar" as const,
      color: t.side === "buy" ? UP : DOWN,
      shape: t.side === "buy" ? "arrowUp" as const : "arrowDown" as const,
      text: t.side === "buy" ? "B" : "S",
    })).sort((a, b) => a.time.localeCompare(b.time));
    createSeriesMarkers(s, markers);
    chart.timeScale().fitContent();
  }, [chart, bars, res]);
  if (!bars.length) return <p className="py-4 text-center text-sm text-slate-500">K线数据不可用，无法绘制交易点</p>;
  return <div ref={ref} className="w-full" />;
}
