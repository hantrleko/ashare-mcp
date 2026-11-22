import { useEffect, useRef, useState, type ReactNode } from "react";
import { createChart, type IChartApi, type DeepPartial, type ChartOptions } from "lightweight-charts";
import { pctClass, fmtPct, fmtPrice } from "../format";
import { cssVar, onThemeChange } from "../theme";

function chartTheme(): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { color: "transparent" },
      textColor: cssVar("--color-chart-text"),
      fontFamily: "Segoe UI, Microsoft YaHei, sans-serif",
    },
    grid: {
      vertLines: { color: "color-mix(in srgb, var(--color-line) 55%, transparent)" },
      horzLines: { color: "color-mix(in srgb, var(--color-line) 55%, transparent)" },
    },
    rightPriceScale: { borderColor: cssVar("--color-line") },
    timeScale: { borderColor: cssVar("--color-line"), timeVisible: false },
  };
}

export function Spinner({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 justify-center text-slate-400 text-sm">
      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-500 border-t-transparent" />
      {label}
    </div>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 py-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-5 animate-pulse rounded bg-panel2" />
      ))}
    </div>
  );
}

export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex items-center justify-between gap-3 rounded border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-300">
      <span className="truncate">数据获取失败：{msg}</span>
      {onRetry && (
        <button onClick={onRetry} className="shrink-0 rounded border border-red-800 px-2 py-0.5 text-xs hover:bg-red-900/40">
          重试
        </button>
      )}
    </div>
  );
}

export function Card({ title, children, className = "", extra }: {
  title?: string; children: ReactNode; className?: string; extra?: ReactNode;
}) {
  return (
    <section className={`rounded-lg border border-line bg-panel p-4 ${className}`}>
      {(title || extra) && (
        <header className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-medium text-slate-300">{title}</h3>
          {extra}
        </header>
      )}
      {children}
    </section>
  );
}

export function PctText({ v, className = "" }: { v: number | null | undefined; className?: string }) {
  return <span className={`num ${pctClass(v)} ${className}`}>{fmtPct(v)}</span>;
}

export function PriceText({ v, className = "" }: { v: number | null | undefined; className?: string }) {
  return <span className={`num ${className}`}>{fmtPrice(v)}</span>;
}

/** Mount a lightweight-charts chart in a div. Returns the chart api via ref callback. */
export function useChart(opts?: DeepPartial<ChartOptions>) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [chart, setChart] = useState<IChartApi | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const c = createChart(ref.current, {
      ...chartTheme(),
      crosshair: { mode: 0 },
      autoSize: true,
      ...opts,
    });
    chartRef.current = c;
    setChart(c);
    const off = onThemeChange(() => c.applyOptions(chartTheme()));
    return () => {
      off();
      c.remove();
      chartRef.current = null;
      setChart(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return { ref, chart };
}
