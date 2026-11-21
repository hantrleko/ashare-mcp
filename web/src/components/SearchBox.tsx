import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type SearchHit } from "../api";

/** Global stock search: debounced dropdown, Enter/arrows select -> /stock/:code. */
export function SearchBox({ onPick, className = "" }: {
  onPick?: (hit: SearchHit) => void; className?: string;
}) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(-1);
  const nav = useNavigate();
  const boxRef = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const query = q.trim();
    if (!query) { setHits([]); setOpen(false); return; }
    timer.current = setTimeout(async () => {
      try {
        const r = await api.search(query, 8);
        setHits(r.data);
        setOpen(true);
        setIdx(-1);
      } catch {
        setHits([]);
      }
    }, 250);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [q]);

  const pick = (h: SearchHit) => {
    setOpen(false);
    setQ("");
    setHits([]);
    if (onPick) onPick(h);
    else nav(`/stock/${h.code}`);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, hits.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") {
      if (idx >= 0 && hits[idx]) pick(hits[idx]);
      else if (hits.length > 0) pick(hits[0]);
      else if (/^\d{6}$/.test(q.trim())) { setOpen(false); nav(`/stock/${q.trim()}`); }
    } else if (e.key === "Escape") setOpen(false);
  };

  return (
    <div ref={boxRef} className={`relative ${className}`}>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={onKey}
        onFocus={() => hits.length && setOpen(true)}
        placeholder="搜索代码 / 名称，如 600519 · 茅台"
        className="w-full rounded border border-line bg-panel2 px-3 py-1.5 text-sm outline-none placeholder:text-slate-500 focus:border-slate-500"
      />
      {open && hits.length > 0 && (
        <ul className="absolute z-40 mt-1 w-full overflow-hidden rounded border border-line bg-panel2 shadow-xl">
          {hits.map((h, i) => (
            <li key={h.code}>
              <button
                onMouseEnter={() => setIdx(i)}
                onClick={() => pick(h)}
                className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm ${
                  i === idx ? "bg-slate-700/50" : ""
                }`}
              >
                <span>
                  <span className="num mr-2 text-slate-400">{h.code}</span>
                  {h.name}
                </span>
                <span className="text-xs uppercase text-slate-500">{h.market}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
