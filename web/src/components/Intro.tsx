import { useState } from "react";
import { X } from "lucide-react";
import { PAGE_INTROS, introKey } from "../lib/glossary";

/** 页面顶部一行说明，可关闭（localStorage ashare.intro.<page>）。 */
export function PageIntro({ page }: { page: string }) {
  const [hidden, setHidden] = useState(() => {
    try { return !!localStorage.getItem(introKey(page)); }
    catch { return false; }
  });
  const text = PAGE_INTROS[page];
  if (!text || hidden) return null;
  return (
    <p className="mb-3 flex items-start gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
      <span className="flex-1">{text}</span>
      <button
        type="button"
        className="shrink-0 cursor-pointer whitespace-nowrap text-muted-foreground/70 transition-colors hover:text-foreground"
        onClick={() => {
          try { localStorage.setItem(introKey(page), "1"); } catch { /* */ }
          setHidden(true);
        }}
      >
        知道了 <X className="inline size-3" aria-hidden />
      </button>
    </p>
  );
}
