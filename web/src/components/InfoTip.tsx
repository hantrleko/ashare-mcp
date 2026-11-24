import { useEffect, useRef, useState } from "react";
import { CircleHelp } from "lucide-react";
import { GLOSSARY, FACTOR_TIPS } from "../lib/glossary";

/** 术语问号图标：hover/focus/click 弹出解释，Esc 或点击外部关闭。 */
export function InfoTip({ term, text, label }: {
  term: string; text?: string; label?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const body = text ?? GLOSSARY[term] ?? FACTOR_TIPS[term] ?? term;
  const head = label ?? term;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [open]);

  return (
    <span
      ref={ref}
      className="relative inline-flex align-middle"
      onPointerEnter={(e) => { if (e.pointerType === "mouse") setOpen(true); }}
    >
      <button
        type="button"
        aria-label={`什么是${head}`}
        className="inline-flex cursor-pointer items-center text-muted-foreground/60 transition-colors hover:text-muted-foreground focus-visible:outline-none focus-visible:text-foreground"
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        onFocus={() => setOpen(true)}
      >
        <CircleHelp className="size-3" />
      </button>
      {open && (
        <span
          role="tooltip"
          className="absolute left-1/2 top-full z-50 mt-1.5 w-56 -translate-x-1/2 rounded-md border border-border bg-popover px-2.5 py-2 text-xs font-normal normal-case leading-relaxed text-popover-foreground shadow-lg"
        >
          <span className="mb-0.5 block font-medium text-foreground">{head}</span>
          {body}
        </span>
      )}
    </span>
  );
}
