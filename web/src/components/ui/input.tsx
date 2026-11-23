import * as React from "react";
import { cn } from "@/lib/utils";

export const inputCls =
  "rounded-md border border-border bg-muted px-2.5 py-1.5 text-sm text-foreground " +
  "outline-none transition-colors duration-150 placeholder:text-muted-foreground " +
  "focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40";

function Input({ className, ...props }: React.ComponentProps<"input">) {
  return <input className={cn(inputCls, className)} {...props} />;
}

function Select({ className, ...props }: React.ComponentProps<"select">) {
  return <select className={cn(inputCls, className)} {...props} />;
}

function Label({ className, ...props }: React.ComponentProps<"label">) {
  return (
    <label
      className={cn("mb-1 block text-xs text-muted-foreground", className)}
      {...props}
    />
  );
}

export { Input, Select, Label };
