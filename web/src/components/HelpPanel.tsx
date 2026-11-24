import { useEffect, useMemo, useRef, useState } from "react";
import { CircleHelp, RotateCcw, Search, X } from "lucide-react";
import { GLOSSARY, FACTOR_TIPS, resetIntros } from "../lib/glossary";
import { Input } from "./ui/input";

const ALL_TERMS: [string, string][] = [
  ...Object.entries(GLOSSARY),
  ...Object.entries(FACTOR_TIPS).map(([, v]) => {
    const i = v.indexOf("：");
    return i < 0 ? [v, v] as [string, string]
                 : [v.slice(0, i), v.slice(i + 1)] as [string, string];
  }),
];

/** 可搜索术语表面板 + 恢复页面说明。 */
export function GlossaryDialog({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [onClose]);

  const items = useMemo(
    () => ALL_TERMS.filter(([k, v]) =>
      !q || k.toLowerCase().includes(q.toLowerCase()) ||
      v.toLowerCase().includes(q.toLowerCase())),
    [q]);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[10vh]">
      <div ref={ref}
        className="w-full max-w-lg rounded-xl border border-border bg-card shadow-xl">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <CircleHelp className="size-4 text-accent" />
          <span className="text-sm font-medium">术语表</span>
          <div className="relative ml-auto w-48">
            <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="搜索术语…" className="h-7 pl-7 text-xs" />
          </div>
          <button type="button" aria-label="关闭术语表" onClick={onClose}
            className="cursor-pointer text-muted-foreground hover:text-foreground">
            <X className="size-4" />
          </button>
        </div>
        <div className="max-h-[55vh] space-y-3 overflow-y-auto px-4 py-3">
          {items.map(([k, v]) => (
            <div key={k}>
              <div className="text-sm font-medium text-foreground">{k}</div>
              <div className="text-xs leading-relaxed text-muted-foreground">{v}</div>
            </div>
          ))}
          {!items.length && (
            <p className="py-6 text-center text-xs text-muted-foreground">没有匹配的术语</p>
          )}
        </div>
        <div className="border-t border-border px-4 py-2.5">
          <button type="button"
            className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            onClick={() => { resetIntros(); onClose(); }}>
            <RotateCcw className="size-3.5" /> 重新显示页面说明
          </button>
        </div>
      </div>
    </div>
  );
}
