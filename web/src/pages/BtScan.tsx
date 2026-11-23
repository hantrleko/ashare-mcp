/** 参数扫描 tab — IS/OOS grid search. */
import { useMemo, useState } from "react";
import { api, type ScanMetrics, type ScanResult } from "../api";
import { Card, ErrorBanner } from "../components/ui";
import { SearchBox } from "../components/SearchBox";
import { Field, inp } from "../components/bt_shared";
import { DOWN, UP, ddClass, fmtDD, fmtPct, signedClass, todayYmd } from "../format";
import { ArrowDown, ArrowUp, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const SCAN_PARAMS: Record<string, [string, string, number, number, number][]> = {
  // key, label, default start, default stop, default step
  ma_cross: [["fast", "快线周期", 5, 20, 5], ["slow", "慢线周期", 30, 120, 30]],
  momentum: [["lookback", "回望天数", 10, 60, 10], ["threshold", "动量阈值", 0.01, 0.05, 0.01]],
  grid: [["grids", "网格数", 5, 20, 5], ["calib", "校准K线", 30, 120, 30]],
};
const METRICS: [string, string][] = [
  ["sharpe", "Sharpe"], ["total_return", "总收益"],
  ["annual_return", "年化收益"], ["max_drawdown", "最大回撤"],
];
type Range = { lo: string; hi: string; st: string };

export default function BtScan() {
  const [symbol, setSymbol] = useState("600519");
  const [strategy, setStrategy] = useState("ma_cross");
  const [ranges, setRanges] = useState<Record<string, Range>>(() =>
    Object.fromEntries(SCAN_PARAMS.ma_cross.map(([k, , a, b, s]) =>
      [k, { lo: String(a), hi: String(b), st: String(s) }])));
  const [start, setStart] = useState("20200101");
  const [end, setEnd] = useState(todayYmd());
  const [split, setSplit] = useState(70);
  const [metric, setMetric] = useState("sharpe");
  const [res, setRes] = useState<ScanResult | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [sortKey, setSortKey] = useState("is");

  const grid = useMemo(() => {
    const g: Record<string, number[]> = {};
    for (const [k] of SCAN_PARAMS[strategy]) {
      const r = ranges[k];
      const lo = Number(r?.lo), hi = Number(r?.hi), st = Number(r?.st);
      const vals: number[] = [];
      if (Number.isFinite(lo) && Number.isFinite(hi) && st > 0 && hi >= lo) {
        for (let v = lo; v <= hi + 1e-9; v += st) vals.push(Number(v.toFixed(6)));
        if (vals.length > 50) vals.length = 50;
      }
      g[k] = vals;
    }
    return g;
  }, [strategy, ranges]);
  const combos = Object.values(grid).reduce((a, v) => a * Math.max(v.length, 1), 1);

  const run = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      setRes(await api.backtestScan({
        symbol, strategy, grid, start, end, split: split / 100,
        metric, capital: 1_000_000, slippage_bps: 0, min_trade_value: 5000,
      }));
    } catch (e) { setErr(e); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        在样本内（前{split}%）优化指标，再检验样本外表现 · 参数组合 ≤ 100 · buy_hold 不可扫描
      </p>
      <Card title="扫描参数">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <div>
            <Label>代码</Label>
            <Input value={symbol} onChange={(e) => setSymbol(e.target.value)} className={inp} />
            <SearchBox className="mt-1" onPick={(h) => setSymbol(h.code)} />
          </div>
          <Field label="策略">
            <select value={strategy} onChange={(e) => {
              const s = e.target.value;
              setStrategy(s);
              setRanges(Object.fromEntries(SCAN_PARAMS[s].map(([k, , a, b, st]) =>
                [k, { lo: String(a), hi: String(b), st: String(st) }])));
            }} className={inp}>
              {Object.keys(SCAN_PARAMS).map((k) => (
                <option key={k} value={k}>
                  {k === "ma_cross" ? "均线交叉" : k === "momentum" ? "动量" : "网格"}
                </option>
              ))}
            </select>
          </Field>
          <Field label="开始日期"><input value={start} onChange={(e) => setStart(e.target.value)} className={inp} /></Field>
          <Field label="结束日期"><input value={end} onChange={(e) => setEnd(e.target.value)} className={inp} /></Field>
          <Field label={`样本内占比 ${split}%`}>
            <input type="range" min={50} max={85} value={split}
              onChange={(e) => setSplit(Number(e.target.value))} className="mt-2 w-full" />
          </Field>
          <Field label="优化指标">
            <select value={metric} onChange={(e) => setMetric(e.target.value)} className={inp}>
              {METRICS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </Field>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {SCAN_PARAMS[strategy].map(([k, label]) => (
            <div key={k} className="flex items-center gap-2">
              <span className="w-20 shrink-0 text-xs text-slate-500">{label}</span>
              {(["lo", "hi", "st"] as const).map((f, j) => (
                <input key={f} value={ranges[k]?.[f] ?? ""} placeholder={["起", "止", "步长"][j]}
                  onChange={(e) => setRanges((r) => ({
                    ...r, [k]: { ...r[k], [f]: e.target.value },
                  }))}
                  className={`${inp} min-w-0 flex-1`} />
              ))}
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={run} disabled={busy || combos > 100 || combos === 0}
            className="px-6">
            {busy ? "扫描中…" : "运行扫描"}
          </Button>
          <span className={`text-xs ${combos > 100 ? "text-down" : "text-slate-500"}`}>
            {combos} 组参数{combos > 100 && "（超过 100 上限，请缩小范围）"}
          </span>
        </div>
      </Card>
      <ErrorBanner error={err} />
      {res && <ScanOut res={res} metric={metric} sortKey={sortKey} setSortKey={setSortKey} />}
    </div>
  );
}

const fmtM = (k: keyof ScanMetrics, v: number) =>
  k === "num_trades" ? String(v)
    : k === "sharpe" ? v.toFixed(2)
    : k === "max_drawdown" ? fmtDD(v * 100) : fmtPct(v * 100);
const clsM = (k: keyof ScanMetrics, v: number) =>
  k === "max_drawdown" ? ddClass(v) : signedClass(v);

function ScanOut({ res, metric, sortKey, setSortKey }: {
  res: ScanResult; metric: string;
  sortKey: string; setSortKey: (k: string) => void;
}) {
  const bestKey = JSON.stringify(res.best_is.params);
  const sorted = [...res.results].sort((a, b) => {
    const [sec, ord] = sortKey.startsWith("!") ? [sortKey.slice(1), 1] : [sortKey, -1];
    const av = (sec === "is" ? a.is : a.oos)[metric as keyof ScanMetrics] ?? 0;
    const bv = (sec === "is" ? b.is : b.oos)[metric as keyof ScanMetrics] ?? 0;
    return (av - bv) * ord;
  });
  return (
    <>
      <Card title="样本内最优">
        <div className="text-sm">
          <span className="num text-lg font-medium text-accent">
            {Object.entries(res.best_is.params).map(([k, v]) => `${k}=${v}`).join("  ")}
          </span>
          <span className="ml-3 text-slate-400">
            样本外{METRICS.find(([k]) => k === metric)?.[1]}{" "}
            <b className={signedClass(res.best_is.oos[metric as keyof ScanMetrics])}>
              {fmtM(metric as keyof ScanMetrics,
                    res.best_is.oos[metric as keyof ScanMetrics])}
            </b>{" "}
            · 样本内最优在样本外排第 <b>{res.oos_rank_of_best_is}</b> / {res.num_combos}
            {res.skipped.length > 0 && ` · 跳过 ${res.skipped.length} 组无效组合`}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">{res.split_date} 前为样本内</p>
      </Card>

      {res.axes && res.axes.names.length === 2 && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card title="样本内">
            <Heatmap res={res} sec="is" metric={metric} bestKey={bestKey} />
          </Card>
          <Card title="样本外">
            <Heatmap res={res} sec="oos" metric={metric} bestKey={bestKey} />
          </Card>
        </div>
      )}

      <Card title={`全部组合（${res.num_combos}）`}>
        <div className="max-h-96 overflow-auto">
          <Table className="whitespace-nowrap text-xs">
            <TableHeader className="sticky top-0 bg-card">
              <TableRow className="hover:bg-transparent">
                <TableHead>参数</TableHead>
                {[["is", "样本内"], ["oos", "样本外"]].map(([k, l]) => (
                  <TableHead key={k} className="cursor-pointer select-none hover:text-foreground"
                    onClick={() => setSortKey(sortKey === k ? `!${k}` : k)}>
                    <span className="inline-flex items-center gap-0.5">
                      {l}
                      {sortKey.replace("!", "") === k && (sortKey.startsWith("!")
                        ? <ArrowUp className="size-3 text-accent" />
                        : <ArrowDown className="size-3 text-accent" />)}
                    </span>
                  </TableHead>
                ))}
                {["total_return", "annual_return", "sharpe", "max_drawdown", "num_trades"]
                  .filter((m) => m !== metric).slice(0, 3)
                  .map((m) => <TableHead key={m}>IS·{m === "total_return" ? "总收益" : m === "annual_return" ? "年化" : m === "sharpe" ? "Sharpe" : m === "max_drawdown" ? "回撤" : "笔数"}</TableHead>)}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((r, i) => {
                const isBest = JSON.stringify(r.params) === bestKey;
                return (
                  <TableRow key={i} className={`hover:bg-muted/50 ${isBest ? "bg-accent/10" : ""}`}>
                    <TableCell className="num">
                      {Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(" ")}
                      {isBest && <Star className="ml-1 inline size-3 fill-accent text-accent" />}
                    </TableCell>
                    <TableCell className={`num ${clsM(metric as keyof ScanMetrics, r.is[metric as keyof ScanMetrics])}`}>
                      {fmtM(metric as keyof ScanMetrics, r.is[metric as keyof ScanMetrics])}
                    </TableCell>
                    <TableCell className={`num ${clsM(metric as keyof ScanMetrics, r.oos[metric as keyof ScanMetrics])}`}>
                      {fmtM(metric as keyof ScanMetrics, r.oos[metric as keyof ScanMetrics])}
                    </TableCell>
                    {["total_return", "annual_return", "sharpe", "max_drawdown", "num_trades"]
                      .filter((m) => m !== metric).slice(0, 3)
                      .map((m) => (
                        <TableCell key={m} className={`num ${clsM(m as keyof ScanMetrics, r.is[m as keyof ScanMetrics])}`}>
                          {fmtM(m as keyof ScanMetrics, r.is[m as keyof ScanMetrics])}
                        </TableCell>))}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </Card>
      <p className="text-xs text-slate-500">{res.notes.join(" · ")}</p>
    </>
  );
}

function Heatmap({ res, sec, metric, bestKey }: {
  res: ScanResult; sec: "is" | "oos"; metric: string; bestKey: string;
}) {
  const [xName, yName] = res.axes!.names;
  const xs = res.axes!.values[xName];
  const ys = res.axes!.values[yName];
  const cell = new Map(res.results.map((r) => [
    `${r.params[yName]}|${r.params[xName]}`,
    r[sec][metric as keyof ScanMetrics] as number]));
  const vals = [...cell.values()];
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const color = (v: number | undefined) => {
    if (v == null || !Number.isFinite(v)) return "transparent";
    const t = hi === lo ? 0.5 : (v - lo) / (hi - lo);
    // interpolate down (green, low) -> up (red, high)
    const base = t >= 0.5 ? UP : DOWN;
    return `color-mix(in srgb, ${base} ${15 + 70 * Math.abs(t - 0.5) * 2}%, transparent)`;
  };
  return (
    <div className="overflow-x-auto">
      <table className="text-center text-xs">
        <thead>
          <tr className="text-slate-500">
            <th className="px-1 py-0.5 font-normal">{yName}\{xName}</th>
            {xs.map((x) => <th key={x} className="num px-1 py-0.5 font-normal">{x}</th>)}
          </tr>
        </thead>
        <tbody>
          {[...ys].reverse().map((y) => (
            <tr key={y}>
              <td className="num px-1 py-0.5 text-slate-400">{y}</td>
              {xs.map((x) => {
                const params: Record<string, number> = { [xName]: x, [yName]: y };
                const v = cell.get(`${y}|${x}`);
                const isBest = JSON.stringify(params) === bestKey;
                return (
                  <td key={x} className="num px-1 py-0.5"
                    style={{
                      background: color(v),
                      outline: isBest ? "2px solid var(--color-accent)" : undefined,
                      outlineOffset: -2,
                    }}>
                    {v != null && Number.isFinite(v)
                      ? (metric === "sharpe" ? v.toFixed(2) : (v * 100).toFixed(1))
                      : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
