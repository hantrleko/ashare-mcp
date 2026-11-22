/** 组合回测 tab — multi-stock equal/inverse-vol portfolio backtest. */
import { useEffect, useRef, useState } from "react";
import { LineSeries } from "lightweight-charts";
import { api, type PortfolioResult, type SearchHit } from "../api";
import { Card, ErrorBanner } from "../components/ui";
import { useChart } from "../components/chart";
import { SearchBox } from "../components/SearchBox";
import { Field, M, inp, toDay, DrawdownChart, MonthlyHeatmap } from "../components/bt_shared";
import { DOWN, UP, fmtNum, fmtPct, fmtSigned, signedClass, todayYmd } from "../format";

const BENCH = [
  { k: "sh000300", label: "沪深300" },
  { k: "sh000905", label: "中证500" },
  { k: "sh000001", label: "上证指数" },
];

export default function BtPortfolio({ initial, autoRun }: {
  initial: { codes: string[] };
  autoRun: boolean;
}) {
  const [codes, setCodes] = useState<string[]>(initial.codes);
  const [names, setNames] = useState<Record<string, string>>({});
  const [weighting, setWeighting] = useState("equal");
  const [reb, setReb] = useState("M");
  const [bench, setBench] = useState("sh000300");
  const [start, setStart] = useState("20220101");
  const [end, setEnd] = useState(todayYmd());
  const [capital, setCapital] = useState(1_000_000);
  const [slip, setSlip] = useState(0);
  const [res, setRes] = useState<PortfolioResult | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const ran = useRef(false);

  const addCode = (h: SearchHit) => {
    setCodes((c) => (c.includes(h.code) || c.length >= 50 ? c : [...c, h.code]));
    setNames((n) => ({ ...n, [h.code]: h.name }));
  };

  const run = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      setRes(await api.backtestPortfolio({
        symbols: codes, weighting, rebalance: reb, start, end,
        capital, slippage_bps: slip, min_trade_value: 5000, benchmark: bench,
      }));
    } catch (e) { setErr(e); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    if (autoRun && !ran.current && codes.length >= 2) {
      ran.current = true;
      run();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        每周/月/季首个交易日按前一收盘权重开盘调仓（先卖后买）· 停牌按最近收盘估值当日不交易 · 涨跌停开盘无法成交
      </p>
      <Card title="组合参数">
        <div className="mb-2 flex flex-wrap gap-1.5">
          {codes.map((c) => (
            <span key={c} className="flex items-center gap-1 rounded bg-panel2 px-2 py-1 text-xs">
              <span className="num">{c}</span>{names[c] ?? ""}
              <button onClick={() => setCodes(codes.filter((x) => x !== c))}
                className="text-slate-500 hover:text-slate-200">×</button>
            </span>
          ))}
          {codes.length === 0 && <span className="text-xs text-slate-500">添加 2–50 只股票</span>}
        </div>
        <SearchBox className="mb-3" onPick={addCode} />
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Field label="权重">
            <select value={weighting} onChange={(e) => setWeighting(e.target.value)} className={inp}>
              <option value="equal">等权</option>
              <option value="inverse_vol">波动率倒数</option>
            </select>
          </Field>
          <Field label="调仓频率">
            <select value={reb} onChange={(e) => setReb(e.target.value)} className={inp}>
              <option value="W">每周</option>
              <option value="M">每月</option>
              <option value="Q">每季</option>
            </select>
          </Field>
          <Field label="基准">
            <select value={bench} onChange={(e) => setBench(e.target.value)} className={inp}>
              {BENCH.map((b) => <option key={b.k} value={b.k}>{b.label} {b.k}</option>)}
            </select>
          </Field>
          <Field label="开始日期"><input value={start} onChange={(e) => setStart(e.target.value)} className={inp} /></Field>
          <Field label="结束日期"><input value={end} onChange={(e) => setEnd(e.target.value)} className={inp} /></Field>
          <Field label="初始资金"><input type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} className={inp} /></Field>
          <Field label="滑点(bps)"><input type="number" value={slip} onChange={(e) => setSlip(Number(e.target.value))} className={inp} /></Field>
          <div className="flex items-end">
            <button onClick={run} disabled={busy || codes.length < 2}
              className="w-full rounded bg-up/90 py-1.5 text-sm font-medium text-white hover:bg-up disabled:opacity-40">
              {busy ? "回测中…" : "运行回测"}
            </button>
          </div>
        </div>
      </Card>
      <ErrorBanner error={err} />
      {res && <PfResult res={res} names={names} />}
    </div>
  );
}

function PfResult({ res, names }: { res: PortfolioResult; names: Record<string, string> }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        <M label="总收益" v={fmtPct(res.total_return * 100)} cls={signedClass(res.total_return)} />
        <M label="年化" v={fmtPct(res.annual_return * 100)} cls={signedClass(res.annual_return)} />
        <M label="基准年化" v={fmtPct(res.benchmark_annual_return * 100)} cls={signedClass(res.benchmark_annual_return)} />
        <M label="超额年化" v={fmtPct(res.excess_annual * 100)} cls={signedClass(res.excess_annual)} />
        <M label="最大回撤" v={fmtPct(res.max_drawdown * 100)} cls="text-down" />
        <M label="年换手" v={res.annual_turnover != null ? res.annual_turnover.toFixed(2) + "×" : "—"} />
        <M label="调仓/拦截" v={`${res.num_rebalances}次 / ${res.blocked_orders}笔`} />
      </div>
      <p className="text-xs text-slate-500">
        {res.symbols.join(" ")} · {res.start}–{res.end} · 基准 {res.benchmark}
        {res.skipped_symbols.length > 0 && ` · 跳过 ${res.skipped_symbols.join(",")}`}
      </p>

      <Card title="净值 vs 基准"><PfCurve res={res} /></Card>
      <Card title="回撤"><DrawdownChart curve={res.equity_curve} /></Card>
      {res.monthly_returns.length > 0 && (
        <Card title="月度收益"><MonthlyHeatmap data={res.monthly_returns} /></Card>
      )}
      <Card title="个股盈亏贡献"><Contribution data={res.contribution} /></Card>

      {res.final_holdings.length > 0 && (
        <Card title="期末持仓">
          <div className="overflow-x-auto">
            <table className="w-full whitespace-nowrap text-xs">
              <thead><tr className="border-b border-line text-left text-slate-500">
                {["代码", "名称", "股数", "市值", "权重"].map((h) => <th key={h} className="px-2 py-1.5 font-normal">{h}</th>)}
              </tr></thead>
              <tbody>{res.final_holdings.map((h) => (
                <tr key={h.code} className="border-b border-line/40">
                  <td className="px-2 py-1.5"><a href={`#/stock/${h.code}`} className="num text-accent hover:underline">{h.code}</a></td>
                  <td className="px-2 py-1.5">{h.name || names[h.code] || "—"}</td>
                  <td className="num px-2 py-1.5">{h.shares}</td>
                  <td className="num px-2 py-1.5">{fmtNum(h.value)}</td>
                  <td className="num px-2 py-1.5">{h.weight != null ? fmtPct(h.weight * 100) : "—"}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {res.rebalance_log.length > 0 && (
        <Card title={`调仓记录（最近${res.rebalance_log.length}次）`}>
          <div className="max-h-56 overflow-x-auto">
            <table className="w-full whitespace-nowrap text-xs">
              <thead><tr className="border-b border-line text-left text-slate-500">
                {["日期", "订单数", "成交额"].map((h) => <th key={h} className="px-2 py-1.5 font-normal">{h}</th>)}
              </tr></thead>
              <tbody>{[...res.rebalance_log].reverse().map((l, i) => (
                <tr key={i} className="border-b border-line/40">
                  <td className="num px-2 py-1.5 text-slate-400">{l.date}</td>
                  <td className="num px-2 py-1.5">{l.orders}</td>
                  <td className="num px-2 py-1.5">{fmtNum(l.turnover)}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {res.notes.length > 0 && (
        <p className="text-xs text-slate-500">{res.notes.join(" · ")}</p>
      )}
    </>
  );
}

function PfCurve({ res }: { res: PortfolioResult }) {
  const { ref, chart } = useChart({ height: 320 });
  useEffect(() => {
    if (!chart) return;
    const s1 = chart.addSeries(LineSeries, { color: "#7b7ff2", lineWidth: 2, title: "组合" });
    s1.setData(res.equity_curve.map((p) => ({ time: toDay(p.date), value: p.equity })));
    const s2 = chart.addSeries(LineSeries, { color: "#8b93a7", lineWidth: 1, lineStyle: 2, title: "基准" });
    s2.setData(res.equity_curve.map((p) => ({ time: toDay(p.date), value: p.benchmark })));
    chart.timeScale().fitContent();
  }, [chart, res]);
  return (
    <div>
      <div className="mb-1 flex gap-4 text-xs text-slate-400">
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-[#7b7ff2] align-middle" />组合</span>
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-[#8b93a7] align-middle" />基准</span>
      </div>
      <div ref={ref} className="w-full min-w-0 overflow-hidden" />
    </div>
  );
}

function Contribution({ data }: { data: { code: string; name: string; pnl: number }[] }) {
  const max = Math.max(...data.map((d) => Math.abs(d.pnl)), 1);
  const top = data.slice(0, 15);
  return (
    <div className="space-y-1">
      {top.map((d) => {
        const w = Math.abs(d.pnl) / max * 50;
        const pos = d.pnl >= 0;
        return (
          <div key={d.code} className="flex items-center gap-2 text-xs">
            <a href={`#/stock/${d.code}`} className="num w-14 shrink-0 text-accent hover:underline">{d.code}</a>
            <span className="w-20 shrink-0 truncate">{d.name}</span>
            <div className="relative h-4 min-w-0 flex-1">
              <div className="absolute top-0 h-full rounded-sm"
                style={{
                  left: pos ? "50%" : `${50 - w}%`, width: `${w}%`,
                  background: pos ? UP : DOWN, opacity: 0.8,
                }} />
              <div className="absolute top-0 h-full w-px bg-line" style={{ left: "50%" }} />
            </div>
            <span className={`num w-24 shrink-0 text-right ${signedClass(d.pnl)}`}>{fmtSigned(d.pnl)}</span>
          </div>
        );
      })}
      {data.length > 15 && <p className="text-xs text-slate-500">…共 {data.length} 只</p>}
    </div>
  );
}
