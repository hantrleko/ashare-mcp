import type { ReactNode } from "react";
import { pctClass, fmtPct, fmtPrice } from "../format";

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
    <section className={`rounded-xl border border-border bg-card p-4 text-card-foreground shadow-sm sm:p-5 ${className}`}>
      {(title || extra) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          <h3 className="text-sm font-medium tracking-tight text-foreground">{title}</h3>
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
