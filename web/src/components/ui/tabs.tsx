import { cn } from "@/lib/utils";

/** Small segmented-control used for option groups and page tabs.
 *  behaviour: single select, controlled. */
export function Seg({ options, value, onChange, className, btnClassName }: {
  options: [string, string][];
  value: string;
  onChange: (v: string) => void;
  className?: string;
  btnClassName?: string;
}) {
  return (
    <div className={cn(
      "inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5",
      className,
    )}>
      {options.map(([v, l]) => (
        <button
          key={v}
          onClick={() => onChange(v)}
          className={cn(
            "cursor-pointer whitespace-nowrap rounded-md px-2.5 py-1 text-xs transition-colors duration-150",
            v === value
              ? "bg-card text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
            btnClassName,
          )}
        >
          {l}
        </button>
      ))}
    </div>
  );
}
