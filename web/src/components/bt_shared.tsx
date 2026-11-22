/** Shared backtest-page building blocks (metrics card, fields, charts). */
import { useEffect } from "react";
import { AreaSeries } from "lightweight-charts";
import { useChart } from "./chart";
import { DOWN, UP } from "../format";
import type { EquityPoint } from "../api";

export const inp = "num w-full rounded border border-line bg-panel2 px-2 py-1.5 text-sm outline-none";

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs text-slate-500">{label}</label>
      {children}
    </div>
  );
}

export function M({ label, v, cls = "" }: { label: string; v: string; cls?: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`num text-base font-medium ${cls}`}>{v}</div>
    </div>
  );
}

export const toDay = (d: string) => (d || "").slice(0, 10) as string;

export function DrawdownChart({ curve }: { curve: EquityPoint[] }) {
  const { ref, chart } = useChart({ height: 140 });
  useEffect(() => {
    if (!chart) return;
    let peak = -Infinity;
    const dd = curve.map((p) => {
      peak = Math.max(peak, p.equity);
      return { time: toDay(p.date), value: (p.equity / peak - 1) * 100 };
    });
    const s = chart.addSeries(AreaSeries, {
      lineColor: DOWN, topColor: "transparent",
      bottomColor: "rgba(38,166,154,0.35)", lineWidth: 1,
    });
    s.setData(dd);
    chart.timeScale().fitContent();
  }, [chart, curve]);
  return <div ref={ref} className="w-full min-w-0 overflow-hidden" />;
}

export function MonthlyHeatmap({ data }: { data: { month: string; ret: number }[] }) {
  const byYear = new Map<string, Map<number, number>>();
  let maxAbs = 0;
  for (const m of data) {
    const [y, mo] = m.month.split("-");
    if (!byYear.has(y)) byYear.set(y, new Map());
    byYear.get(y)!.set(Number(mo), m.ret);
    maxAbs = Math.max(maxAbs, Math.abs(m.ret));
  }
  const scale = maxAbs || 1;
  const years = [...byYear.keys()].sort();
  const cell = (r: number | undefined) => {
    if (r == null) return { bg: "transparent", fg: "var(--color-slate-500)" };
    const t = Math.min(Math.abs(r) / scale, 1);
    const base = r >= 0 ? UP : DOWN;
    return {
      bg: `color-mix(in srgb, ${base} ${18 + 62 * t}%, transparent)`,
      fg: "var(--color-slate-100)",
    };
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-center text-xs">
        <thead>
          <tr className="text-slate-500">
            <th className="py-1 text-left font-normal">年份</th>
            {Array.from({ length: 12 }, (_, i) => (
              <th key={i} className="num px-1 py-1 font-normal">{i + 1}月</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((y) => (
            <tr key={y}>
              <td className="num py-0.5 pr-2 text-left text-slate-400">{y}</td>
              {Array.from({ length: 12 }, (_, i) => {
                const r = byYear.get(y)!.get(i + 1);
                const c = cell(r);
                return (
                  <td key={i} className="num px-1 py-0.5">
                    <span className="block rounded px-1 py-0.5"
                          style={{ background: c.bg, color: c.fg }}>
                      {r != null ? `${r >= 0 ? "+" : ""}${r.toFixed(1)}` : ""}
                    </span>
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
