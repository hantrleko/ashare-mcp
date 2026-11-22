/** /factor — single-factor / composite backtests via the job API. */
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { HistogramSeries, LineSeries } from "lightweight-charts";
import {
  api, type FactorInfo, type FactorJobIn, type FactorJobState,
  type FactorResult,
} from "../api";
import { Card, ErrorBanner, Spinner } from "../components/ui";
import { useChart } from "../components/chart";
import { Field, M, inp, toDay } from "../components/bt_shared";
import { DOWN, UP, fmtPct, signedClass } from "../format";

const PALETTE = ["#8b93a7", "#5b8def", "#7b7ff2", "#c084fc", "#f472b6",
  "#fb923c", "#facc15", "#4ade80", "#38bdf8", "#f87171"];

function defStart(): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 3);
  return d.toISOString().slice(0, 10);
}

export default function Factor() {
  const [sp] = useSearchParams();
  const initCodes = (sp.get("codes") || "").split(",").filter(Boolean);
  const [factors, setFactors] = useState<FactorInfo[]>([]);
  const [mode, setMode] = useState<"single" | "composite">("single");
  const [factor, setFactor] = useState("mom_20");
  const [comp, setComp] = useState<{ factor: string; sign: number }[]>([]);
  const [universe, setUniverse] = useState(
    initCodes.length >= 20 ? "custom" : "top_cap");
  const [size, setSize] = useState(100);
  const [symbols, setSymbols] = useState(initCodes.join(","));
  const [start, setStart] = useState(defStart());
  const [end, setEnd] = useState(new Date().toISOString().slice(0, 10));
  const [freq, setFreq] = useState("M");
  const [q, setQ] = useState(5);
  const [job, setJob] = useState<FactorJobState | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.factorList().then((r) => setFactors(r.data)).catch(setErr);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, []);

  const symList = symbols.split(/[,\s]+/).filter(Boolean);
  const body: FactorJobIn = {
    factor,
    composite: mode === "composite" && comp.length ? comp : null,
    universe,
    universe_size: size,
    symbols: universe === "custom" ? symList : null,
    start_date: start, end_date: end, freq, quantiles: q,
  };

  const poll = (id: string) => {
    api.factorJob(id).then((j) => {
      setJob(j);
      if (j.state === "queued" || j.state === "running") {
        timer.current = window.setTimeout(() => poll(id), 2000);
      }
    }).catch(setErr);
  };

  const submit = () => {
    setErr(null); setJob(null);
    api.factorSubmit(body).then((r) => {
      setJob({ job_id: r.job_id, state: "queued",
               progress: { loaded: 0, total: 0, stage: "queued" },
               error: null, result: null });
      poll(r.job_id);
    }).catch(setErr);
  };

  const running = job && (job.state === "queued" || job.state === "running");
  const res = job?.result ?? null;
  const validCustom = universe !== "custom"
    || (symList.length >= 20 && symList.length <= 300);

  return (
    <div className="space-y-4">
      <Card title="因子检验" extra={
        <span className="text-xs text-slate-500">截面 IC · 分位组合 · 多空</span>}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="模式">
            <select className={inp} value={mode}
              onChange={(e) => setMode(e.target.value as typeof mode)}>
              <option value="single">单因子</option>
              <option value="composite">复合因子</option>
            </select>
          </Field>
          {mode === "single" ? (
            <Field label="因子">
              <select className={inp} value={factor}
                onChange={(e) => setFactor(e.target.value)}>
                {factors.map((f) => (
                  <option key={f.id} value={f.id}>{f.name}</option>
                ))}
              </select>
            </Field>
          ) : (
            <div className="col-span-2 sm:col-span-3">
              <label className="mb-1 block text-xs text-slate-500">
                复合因子（点击 +/− 加入）</label>
              <div className="flex flex-wrap gap-1.5">
                {factors.map((f) => (
                  <span key={f.id} className="inline-flex items-center gap-0.5 rounded border border-line px-1.5 py-0.5 text-xs">
                    {f.name}
                    <button className="px-1 text-up hover:font-bold" title="正向"
                      onClick={() => setComp([...comp, { factor: f.id, sign: 1 }])}>+</button>
                    <button className="px-1 text-down hover:font-bold" title="负向"
                      onClick={() => setComp([...comp, { factor: f.id, sign: -1 }])}>−</button>
                  </span>
                ))}
              </div>
              {comp.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {comp.map((c, i) => (
                    <button key={i}
                      onClick={() => setComp(comp.filter((_, j) => j !== i))}
                      className="rounded bg-panel2 px-1.5 py-0.5 text-xs text-slate-300"
                      title="点击移除">
                      {c.sign > 0 ? "+" : "−"}
                      {factors.find((f) => f.id === c.factor)?.name ?? c.factor}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {mode === "single" && (
            <div className="col-span-2 self-end pb-1 text-xs text-slate-500">
              {factors.find((f) => f.id === factor)?.desc}
            </div>
          )}
          <Field label="股票池">
            <select className={inp} value={universe}
              onChange={(e) => setUniverse(e.target.value)}>
              <option value="top_cap">市值前 N</option>
              <option value="custom">自定义代码</option>
            </select>
          </Field>
          {universe === "top_cap" ? (
            <Field label={`前 N = ${size}`}>
              <input type="range" min={20} max={300} step={10} value={size}
                onChange={(e) => setSize(+e.target.value)} className="w-full" />
            </Field>
          ) : (
            <Field label={`代码（${symList.length}，20–300，逗号分隔）`}>
              <input className={inp} value={symbols}
                onChange={(e) => setSymbols(e.target.value)}
                placeholder="600519,000858,..." />
            </Field>
          )}
          <Field label="开始">
            <input type="date" className={inp} value={start}
              onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label="结束">
            <input type="date" className={inp} value={end}
              onChange={(e) => setEnd(e.target.value)} />
          </Field>
          <Field label="调仓频率">
            <select className={inp} value={freq}
              onChange={(e) => setFreq(e.target.value)}>
              <option value="M">月度</option>
              <option value="W">周度</option>
            </select>
          </Field>
          <Field label={`分组数 = ${q}`}>
            <input type="range" min={3} max={10} value={q}
              onChange={(e) => setQ(+e.target.value)} className="w-full" />
          </Field>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button onClick={submit} disabled={!!running || !validCustom
            || (mode === "composite" && comp.length === 0)}
            className="rounded bg-up/90 px-4 py-1.5 text-sm font-medium text-white hover:bg-up disabled:opacity-40">
            {running ? "运行中…" : "开始检验"}
          </button>
          {running && (
            <div className="flex-1">
              <div className="mb-1 flex justify-between text-xs text-slate-500">
                <span>{job!.progress.stage === "kline"
                  ? `加载K线 ${job!.progress.loaded}/${job!.progress.total}`
                  : { queued: "排队中", universe: "构建股票池",
                      factor: "计算因子", test: "截面检验" }[job!.progress.stage]
                    ?? job!.progress.stage}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded bg-panel2">
                <div className="h-full bg-up transition-all"
                  style={{ width: job!.progress.total
                    ? `${(job!.progress.loaded / job!.progress.total) * 100}%`
                    : "5%" }} />
              </div>
            </div>
          )}
        </div>
        {job?.state === "failed" && (
          <div className="mt-3 rounded border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-300">
            {job.error}
          </div>
        )}
      </Card>
      <ErrorBanner error={err} />
      {!res && !running && !job && (
        <Card><div className="py-6 text-center text-sm text-slate-500">
          选择因子与股票池后开始检验。K线首次加载较慢（每只股票约 1 秒），
          同一股票池的后续检验会走缓存。
        </div></Card>
      )}
      {running && !res && <Spinner label="计算中（后台任务）" />}
      {res && <Results res={res} />}
    </div>
  );
}

function Results({ res }: { res: FactorResult }) {
  const rs = res.rank_ic_summary;
  const lsAnn = res.quantile_annual["LS"];
  const topQ = `Q${Math.max(...Object.keys(res.quantile_annual)
    .filter((k) => k.startsWith("Q")).map((k) => +k.slice(1)))}`;
  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        <M label="RankIC 均值" v={fmtNum4(rs.mean)}
          cls={signedClass(rs.mean)} />
        <M label="RankIC IR" v={fmtNum4(rs.icir)} cls={signedClass(rs.icir)} />
        <M label="t 值" v={fmtNum4(rs.t)} cls={signedClass(rs.t)} />
        <M label="IC>0 占比" v={rs.pos_ratio == null ? "—"
          : `${(rs.pos_ratio * 100).toFixed(0)}%`} />
        <M label="IC 均值" v={fmtNum4(res.ic_summary.mean)}
          cls={signedClass(res.ic_summary.mean)} />
        <M label="多空年化" v={fmtPct(lsAnn == null ? null : lsAnn * 100)}
          cls={signedClass(lsAnn)} />
        <M label="头部组换手" v={res.top_turnover == null ? "—"
          : `${(res.top_turnover * 100).toFixed(1)}%`} />
      </div>
      <div className="mt-2 text-xs text-slate-500">
        股票池 {res.universe.count} 只
        {res.universe.dropped.length > 0 &&
          `（剔除 ${res.universe.dropped.length} 只不足${130}根K线：${res.universe.dropped.join(" ")}）`}
        {" · "}有效调仓日 {res.dates_used.length}
        {res.dates_dropped_small.length > 0 &&
          ` · 样本不足剔除 ${res.dates_dropped_small.length} 期`}
      </div>

      <Card title="RankIC（柱）与累计 RankIC（线）">
        <RankICChart res={res} />
      </Card>
      <Card title={`分位组合净值（Q1 因子最低 · LS = ${topQ}−Q1）`}>
        <NavChart res={res} />
      </Card>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="分组年化收益">
          <BarChart data={Object.entries(res.quantile_annual)
            .map(([k, v]) => ({ label: k === "LS" ? `LS(${topQ}−Q1)` : k,
                                v: v == null ? 0 : v * 100 }))} />
        </Card>
        <Card title="IC 衰减（RankIC 均值 × 前第 L 期）">
          <BarChart data={res.ic_decay.map((d) => ({
            label: `L${d.lag}`,
            v: d.rank_ic_mean == null ? 0 : d.rank_ic_mean * 100,
          }))} suffix="%" />
        </Card>
      </div>
      <Card>
        <div className="rounded border border-yellow-800/60 bg-yellow-950/30 px-3 py-2 text-xs leading-6 text-yellow-200/90">
          {res.notes.map((n, i) => <div key={i}>· {n}</div>)}
        </div>
        <button onClick={() => exportIcCsv(res)}
          className="mt-3 rounded border border-line px-3 py-1 text-xs text-slate-300 hover:bg-panel2">
          导出 IC 序列 CSV
        </button>
      </Card>
    </>
  );
}

const fmtNum4 = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "—" : v.toFixed(4);

function RankICChart({ res }: { res: FactorResult }) {
  const { ref, chart } = useChart({ height: 260 });
  useEffect(() => {
    if (!chart) return;
    const hist = chart.addSeries(HistogramSeries, { title: "RankIC" });
    hist.setData(res.ic_series.map((r) => ({
      time: toDay(r.date),
      value: r.rank_ic == null ? 0 : r.rank_ic,
      color: (r.rank_ic ?? 0) >= 0 ? UP : DOWN,
    })));
    let cum = 0;
    const line = chart.addSeries(LineSeries, {
      color: "#facc15", lineWidth: 2, title: "累计",
      priceScaleId: "left",
    });
    chart.priceScale("left").applyOptions({ visible: true });
    line.setData(res.ic_series.map((r) => ({
      time: toDay(r.date),
      value: (cum += r.rank_ic ?? 0),
    })));
    chart.timeScale().fitContent();
  }, [chart, res]);
  return <div ref={ref} className="w-full min-w-0 overflow-hidden" />;
}

function NavChart({ res }: { res: FactorResult }) {
  const { ref, chart } = useChart({ height: 300 });
  useEffect(() => {
    if (!chart) return;
    Object.entries(res.quantile_nav).forEach(([k, pts], i) => {
      const isLS = k === "LS";
      const s = chart.addSeries(LineSeries, {
        color: isLS ? "#f8fafc" : PALETTE[i % PALETTE.length],
        lineWidth: isLS ? 2 : 1,
        lineStyle: isLS ? 2 : 0,
        title: k,
      });
      s.setData(pts.map((p) => ({ time: toDay(p.date), value: p.nav })));
    });
    chart.timeScale().fitContent();
  }, [chart, res]);
  return <div ref={ref} className="w-full min-w-0 overflow-hidden" />;
}

function BarChart({ data, suffix = "%" }:
  { data: { label: string; v: number }[]; suffix?: string }) {
  const max = Math.max(...data.map((d) => Math.abs(d.v)), 1e-9);
  return (
    <div className="space-y-1.5 py-1">
      {data.map((d) => (
        <div key={d.label} className="flex items-center gap-2 text-xs">
          <span className="w-16 shrink-0 text-right text-slate-400">
            {d.label}</span>
          <div className="relative h-4 flex-1 rounded bg-panel2">
            <div className="absolute top-0 h-full rounded"
              style={{
                left: d.v >= 0 ? "50%" : `${50 - (Math.abs(d.v) / max) * 50}%`,
                width: `${(Math.abs(d.v) / max) * 50}%`,
                background: d.v >= 0 ? UP : DOWN,
              }} />
            <div className="absolute left-1/2 top-0 h-full w-px bg-line" />
          </div>
          <span className={`num w-16 shrink-0 ${signedClass(d.v)}`}>
            {d.v.toFixed(2)}{suffix}
          </span>
        </div>
      ))}
    </div>
  );
}

function exportIcCsv(res: FactorResult) {
  const head = "date,ic,rank_ic,n";
  const rows = res.ic_series.map((r) =>
    `${r.date},${r.ic ?? ""},${r.rank_ic ?? ""},${r.n}`);
  const blob = new Blob(["﻿" + [head, ...rows].join("\n")],
    { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `factor_ic_${res.params.factor ?? "x"}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}
