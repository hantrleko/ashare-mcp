// Tremor Raw CategoryBar [derived]
// SPDX-License-Identifier: Apache-2.0
// Source: https://github.com/tremorlabs/tremor (raw component, adapted:
// cx -> cn, tailwind-variants removed, colors via local tokens)
import { cn } from "@/lib/utils";

export interface CategoryBarItem {
  name: string;
  value: number;
  color: string; // css color or token, e.g. "var(--color-up)"
}

/** Stacked proportional bar with optional marker/legend, e.g. for
 *  market breadth 上涨/平盘/下跌. */
export function CategoryBar({
  values,
  marker,
  showLabels = true,
  className,
}: {
  values: CategoryBarItem[];
  /** optional marker position 0-100 */
  marker?: number;
  showLabels?: boolean;
  className?: string;
}) {
  const items = values;
  const sum = items.reduce((s, v) => s + v.value, 0) || 1;
  return (
    <div className={cn("w-full", className)}>
      <div className="relative flex h-2 w-full overflow-hidden rounded-full">
        {items.map((v) => (
          <div
            key={v.name}
            className="h-full transition-all duration-200"
            style={{ width: `${(v.value / sum) * 100}%`, background: v.color }}
          />
        ))}
        {marker != null && (
          <div
            className="absolute top-0 h-full w-0.5 bg-foreground"
            style={{ left: `${Math.min(Math.max(marker, 0), 100)}%` }}
          />
        )}
      </div>
      {showLabels && (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {items.map((v) => (
            <span key={v.name} className="flex items-center gap-1 text-xs text-muted-foreground">
              <span className="inline-block size-2 rounded-full" style={{ background: v.color }} />
              {v.name}
              <span className="num text-foreground">{v.value}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
