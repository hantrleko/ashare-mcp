import * as React from "react";
import { cn } from "@/lib/utils";

/** Lightweight CSS tooltip (no radix): wraps children, shows `content`
 *  on hover/focus via a group class. Not for interactive content. */
function Tooltip({
  content,
  children,
  className,
  side = "top",
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  side?: "top" | "bottom";
}) {
  return (
    <span className="group/tt relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap",
          "rounded-md border border-border bg-popover px-2 py-1 text-xs text-popover-foreground",
          "opacity-0 shadow-md transition-opacity duration-150",
          "group-hover/tt:opacity-100 group-focus-within/tt:opacity-100",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
          className,
        )}
      >
        {content}
      </span>
    </span>
  );
}

export { Tooltip };
