/** lightweight-charts hook — kept separate so the chart lib stays in the
 * lazy vendor_charts chunk and is not loaded by the Home page. */
import { useEffect, useRef, useState } from "react";
import { createChart, type IChartApi, type DeepPartial, type ChartOptions } from "lightweight-charts";
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
