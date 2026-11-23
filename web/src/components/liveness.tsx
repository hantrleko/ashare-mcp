/** Liveness hooks/components: intraday sparkline fetcher (concurrency ≤3,
 *  60 s refresh), price-change flash, market-status pill (CST). */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type IntradayData } from "../api";

/** Fetch intraday series for `symbols` (max 3 in flight), refresh every 60 s. */
export function useSparklines(symbols: string[]): Map<string, IntradayData> {
  const [data, setData] = useState<Map<string, IntradayData>>(new Map());
  const key = symbols.join(",");

  useEffect(() => {
    const syms = key ? key.split(",") : [];
    let alive = true;
    let timer: ReturnType<typeof setInterval>;

    const load = async () => {
      const queue = [...syms];
      const workers = Array.from({ length: Math.min(3, queue.length) }, async () => {
        while (queue.length) {
          const s = queue.shift()!;
          try {
            const r = await api.intraday(s);
            if (!alive) return;
            setData((m) => new Map(m).set(s, r.data));
          } catch { /* keep old */ }
        }
      });
      await Promise.all(workers);
    };

    load();
    timer = setInterval(load, 60_000);
    return () => { alive = false; clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return data;
}

/** Wrapper that flashes its cell background when `value` changes. */
export function PriceFlash({ value, children, className = "" }: {
  value: number | null | undefined; children?: ReactNode; className?: string;
}) {
  const prev = useRef<number | null>(null);
  const [flash, setFlash] = useState<"" | "flash-up" | "flash-down">("");

  useEffect(() => {
    if (value == null || !Number.isFinite(value)) return;
    const old = prev.current;
    prev.current = value;
    if (old != null && value !== old) {
      setFlash(value > old ? "flash-up" : "flash-down");
      const t = setTimeout(() => setFlash(""), 850);
      return () => clearTimeout(t);
    }
  }, [value]);

  return <span className={`${flash} rounded px-0.5 ${className}`}>{children}</span>;
}

type Phase = { label: string; live: boolean };

/** Market phase in Asia/Shanghai. */
export function marketPhase(now = new Date()): Phase {
  const cst = new Date(now.getTime() + (8 * 60 + now.getTimezoneOffset()) * 60000);
  const day = cst.getDay();
  if (day === 0 || day === 6) return { label: "休市", live: false };
  const t = cst.getHours() * 60 + cst.getMinutes();
  if (t < 9 * 60 + 15) return { label: "未开盘", live: false };
  if (t < 9 * 60 + 30) return { label: "集合竞价", live: true };
  if (t < 11 * 60 + 30) return { label: "交易中", live: true };
  if (t < 13 * 60) return { label: "午间休市", live: false };
  if (t < 15 * 60) return { label: "交易中", live: true };
  return { label: "已收盘", live: false };
}

export function MarketStatusPill() {
  const [phase, setPhase] = useState(marketPhase());
  const [holiday, setHoliday] = useState<boolean | null>(null);
  useEffect(() => {
    const t = setInterval(() => setPhase(marketPhase()), 30_000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await api.marketClock();
        if (alive) setHoliday(r.is_trading_day);
      } catch { /* keep local guess */ }
    };
    load();
    const t = setInterval(load, 300_000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  const label = holiday === false ? "休市" : phase.label;
  const live = holiday !== false && phase.label === "交易中";
  return (
    <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-panel px-2 py-0.5 text-xs text-slate-400">
      <span
        className={`h-1.5 w-1.5 rounded-full ${live ? "bg-emerald-400 pulse-dot" : "bg-slate-500"}`}
      />
      {label}
    </span>
  );
}

export function useClockTick(intervalMs = 1000) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
}

export function useMemoNow() {
  return useMemo(() => new Date(), []);
}
