import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type IndustryInfo, type ScreenIn, type ScreenResult, type ScreenRow } from "../api";
import { Card, ErrorBanner, PctText, Skeleton } from "../components/ui";
import { fmtAmount, fmtNum, fmtPrice, signedClass } from "../format";
import { useToast } from "../components/Toast";

const WATCH_KEY = "ashare_watchlist";
const SAVED_KEY = "ashare.screens";

type Bound = { min: string; max: string };
type RangeKey = "price" | "pct_chg" | "turnover" | "pe_ttm" | "pb" | "roe_est"
  | "mkt_cap" | "float_mkt_cap" | "amount" | "volume_ratio" | "amplitude";

const RANGE_DEFS: { k: RangeKey; label: string; unit?: "亿" | "%" }[] = [
  { k: "price", label: "最新价" },
  { k: "pct_chg", label: "涨跌幅", unit: "%" },
  { k: "turnover", label: "换手率", unit: "%" },
  { k: "pe_ttm", label: "PE(TTM)" },
  { k: "pb", label: "PB" },
  { k: "roe_est", label: "ROE估算", unit: "%" },
  { k: "mkt_cap", label: "总市值", unit: "亿" },
  { k: "float_mkt_cap", label: "流通市值", unit: "亿" },
  { k: "amount", label: "成交额", unit: "亿" },
  { k: "volume_ratio", label: "量比" },
  { k: "amplitude", label: "振幅", unit: "%" },
];
const YI = new Set(["mkt_cap", "float_mkt_cap", "amount"]);
const MOM_DEFS = [{ k: "mom_20", label: "20日动量%" }, { k: "mom_60", label: "60日动量%" }] as const;
const BOARDS: { k: string; label: string }[] = [
  { k: "main", label: "主板" }, { k: "chinext", label: "创业板" },
  { k: "star", label: "科创板" }, { k: "bse", label: "北交所" },
];
const BOARD_LABEL = Object.fromEntries(BOARDS.map((b) => [b.k, b.label]));

const PRESETS: { label: string; in_: ScreenIn }[] = [
  { label: "低估值蓝筹", in_: { ranges: { pe_ttm: [0, 15], pb: [0, 1.5], mkt_cap: [500e8, null] } } },
  { label: "高ROE", in_: { ranges: { roe_est: [15, null], pe_ttm: [0, 40] } } },
  { label: "小盘活跃", in_: { ranges: { mkt_cap: [20e8, 100e8], turnover: [5, null] } } },
  { label: "强势动量", in_: { ranges: { mkt_cap: [1000e8, null] }, momentum: { mom_20: [10, null] }, sort_by: "mom_20" } },
];

const SORTABLE = new Set(["code", "name", "industry", ...RANGE_DEFS.map((d) => d.k), "mom_20", "mom_60"]);
const COLS: { k: string; label: string; num?: boolean }[] = [
  { k: "code", label: "代码" }, { k: "name", label: "名称" },
  { k: "industry", label: "行业" }, { k: "board", label: "板块" },
  { k: "price", label: "最新", num: true }, { k: "pct_chg", label: "涨跌幅", num: true },
  { k: "turnover", label: "换手", num: true }, { k: "pe_ttm", label: "PE", num: true },
  { k: "pb", label: "PB", num: true }, { k: "roe_est", label: "ROE", num: true },
  { k: "mkt_cap", label: "总市值", num: true }, { k: "amount", label: "成交额", num: true },
  { k: "volume_ratio", label: "量比", num: true },
];

interface FormState {
  ranges: Record<RangeKey, Bound>;
  mom: Record<"mom_20" | "mom_60", Bound>;
  inds: string[]; boards: string[]; exSt: boolean; exSusp: boolean;
}

const emptyBound = (): Bound => ({ min: "", max: "" });
const emptyForm = (): FormState => ({
  ranges: Object.fromEntries(RANGE_DEFS.map((d) => [d.k, emptyBound()])) as FormState["ranges"],
  mom: { mom_20: emptyBound(), mom_60: emptyBound() },
  inds: [], boards: [], exSt: true, exSusp: true,
});

function toNum(s: string): number | null {
  const t = s.trim();
  if (!t) return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}

function formToIn(f: FormState, sort_by: string, desc: boolean): ScreenIn {
  const ranges: ScreenIn["ranges"] = {};
  for (const d of RANGE_DEFS) {
    const b = f.ranges[d.k];
    const lo = toNum(b.min), hi = toNum(b.max);
    if (lo === null && hi === null) continue;
    const scale = YI.has(d.k) ? 1e8 : 1;
    ranges[d.k] = [lo === null ? null : lo * scale, hi === null ? null : hi * scale];
  }
  const momentum: ScreenIn["momentum"] = {};
  for (const d of MOM_DEFS) {
    const b = f.mom[d.k];
    const lo = toNum(b.min), hi = toNum(b.max);
    if (lo !== null || hi !== null) momentum[d.k] = [lo, hi];
  }
  return {
    ranges, industries: f.inds, boards: f.boards,
    exclude_st: f.exSt, exclude_suspended: f.exSusp,
    momentum, sort_by, desc, limit: 200,
  };
}

function inToForm(i: ScreenIn): FormState {
  const f = emptyForm();
  for (const d of RANGE_DEFS) {
    const rng = i.ranges?.[d.k];
    if (!rng) continue;
    const scale = YI.has(d.k) ? 1e8 : 1;
    f.ranges[d.k] = {
      min: rng[0] === null ? "" : String(rng[0] / scale),
      max: rng[1] === null ? "" : String(rng[1] / scale),
    };
  }
  for (const d of MOM_DEFS) {
    const rng = i.momentum?.[d.k];
    if (rng) f.mom[d.k] = { min: rng[0] === null ? "" : String(rng[0]), max: rng[1] === null ? "" : String(rng[1]) };
  }
  f.inds = i.industries ?? [];
  f.boards = i.boards ?? [];
  f.exSt = i.exclude_st ?? true;
  f.exSusp = i.exclude_suspended ?? true;
  return f;
}

function loadSaved(): Record<string, ScreenIn> {
  try {
    const v = JSON.parse(localStorage.getItem(SAVED_KEY) || "null");
    if (v && typeof v === "object") return v;
  } catch { /* fall through */ }
  return {};
}

function addWatch(code: string) {
  try {
    const v = JSON.parse(localStorage.getItem(WATCH_KEY) || "null");
    const arr = Array.isArray(v) ? v : [];
    if (!arr.includes(code)) {
      arr.push(code);
      localStorage.setItem(WATCH_KEY, JSON.stringify(arr));
    }
    return true;
  } catch { return false; }
}

function cell(k: string, r: ScreenRow) {
  const v = r[k as keyof ScreenRow] as number | string | null | undefined;
  switch (k) {
    case "code":
      return <Link className="text-slate-200 hover:text-up hover:underline" to={`/stock/${r.code}`}>{r.code}</Link>;
    case "board": return BOARD_LABEL[r.board] ?? r.board;
    case "price": return fmtPrice(v as number);
    case "pct_chg": return <PctText v={(v as number) ?? null} />;
    case "turnover": return v == null ? "—" : `${fmtNum(v as number, 2)}%`;
    case "pe_ttm": case "pb": return v == null ? "—" : fmtNum(v as number, 2);
    case "roe_est": return v == null ? "—" : `${fmtNum(v as number, 1)}%`;
    case "mkt_cap": case "float_mkt_cap": case "amount": return fmtAmount(v as number);
    case "volume_ratio": return v == null ? "—" : fmtNum(v as number, 2);
    case "mom_20": case "mom_60":
      return v == null ? "—" : <span className={signedClass(v as number)}>{fmtNum(v as number, 1)}%</span>;
    default: return v ?? "—";
  }
}

export default function Screener() {
  const [form, setForm] = useState<FormState>(emptyForm);
  const [sort, setSort] = useState<{ by: string; desc: boolean }>({ by: "mkt_cap", desc: true });
  const [industries, setIndustries] = useState<IndustryInfo[]>([]);
  const [indQ, setIndQ] = useState("");
  const [res, setRes] = useState<ScreenResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [momPending, setMomPending] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [saved, setSaved] = useState<Record<string, ScreenIn>>(loadSaved);
  const [saveName, setSaveName] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const toast = useToast();

  useEffect(() => { api.industries().then((r) => setIndustries(r.data)).catch(() => {}); }, []);

  const run = useCallback(async (by = sort.by, desc = sort.desc, f = form) => {
    setLoading(true); setErr(null);
    const req_ = formToIn(f, by, desc);
    setMomPending(!!Object.keys(req_.momentum ?? {}).length || ["mom_20", "mom_60"].includes(by));
    try {
      const r = await api.screen(req_);
      setRes(r); setSel(new Set());
    } catch (e) { setErr(e); setRes(null); }
    finally { setLoading(false); setMomPending(false); }
  }, [form, sort]);

  const clickSort = (k: string) => {
    if (!SORTABLE.has(k)) return;
    const desc = sort.by === k ? !sort.desc : true;
    setSort({ by: k, desc });
    run(k, desc);
  };

  const applyPreset = (i: ScreenIn) => {
    const f = inToForm(i);
    setForm(f);
    const by = i.sort_by ?? "mkt_cap";
    setSort({ by, desc: i.desc ?? true });
    run(by, i.desc ?? true, f);
  };

  const indShown = useMemo(
    () => industries.filter((i) => !indQ || i.name.includes(indQ)),
    [industries, indQ]);

  const saveCurrent = () => {
    const name = saveName.trim();
    if (!name) return;
    const next = { ...saved, [name]: formToIn(form, sort.by, sort.desc) };
    localStorage.setItem(SAVED_KEY, JSON.stringify(next));
    setSaved(next); setSaveName("");
    toast("ok", `已保存筛选「${name}」`);
  };

  const exportCsv = () => {
    if (!res) return;
    const momCols = res.rows.some((r) => r.mom_20 != null || r.mom_60 != null);
    const heads = [...COLS.map((c) => c.label), ...(momCols ? ["20日动量", "60日动量"] : [])];
    const raw = (k: string, r: ScreenRow) => r[k as keyof ScreenRow] ?? "";
    const lines = [heads.join(",")].concat(
      res.rows.map((r) => [...COLS.map((c) => raw(c.k, r)),
        ...(momCols ? [r.mom_20 ?? "", r.mom_60 ?? ""] : [])]
        .map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")));
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `screen_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const boundInput = (k: RangeKey | "mom_20" | "mom_60", which: "min" | "max") => (
    <input
      value={k in form.ranges ? form.ranges[k as RangeKey][which] : form.mom[k as "mom_20"][which]}
      onChange={(e) => {
        const v = e.target.value;
        setForm((f) => k in f.ranges
          ? { ...f, ranges: { ...f.ranges, [k]: { ...f.ranges[k as RangeKey], [which]: v } } }
          : { ...f, mom: { ...f.mom, [k]: { ...f.mom[k as "mom_20" | "mom_60"], [which]: v } } });
      }}
      placeholder={which === "min" ? "最小" : "最大"}
      className="num w-14 rounded border border-line bg-panel2 px-1.5 py-0.5 text-right text-xs outline-none"
    />
  );

  return (
    <div className="space-y-4">
      <Card title="选股器" extra={
        <button onClick={() => setFiltersOpen(!filtersOpen)}
          className="rounded border border-line px-2 py-0.5 text-xs text-slate-400 hover:bg-panel2 sm:hidden">
          {filtersOpen ? "收起" : "展开"}
        </button>
      }>
        <div className={`space-y-3 ${filtersOpen ? "" : "max-sm:hidden"}`}>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-slate-500">预设</span>
            {PRESETS.map((p) => (
              <button key={p.label} onClick={() => applyPreset(p.in_)}
                className="rounded border border-line px-2 py-1 text-slate-300 hover:bg-panel2">
                {p.label}
              </button>
            ))}
            <span className="mx-1 hidden h-4 w-px bg-line sm:block" />
            <input value={saveName} onChange={(e) => setSaveName(e.target.value)}
              placeholder="方案名" className="w-20 rounded border border-line bg-panel2 px-1.5 py-1 text-xs outline-none" />
            <button onClick={saveCurrent} className="rounded border border-line px-2 py-1 text-xs text-slate-300 hover:bg-panel2">保存当前条件</button>
            {Object.keys(saved).length > 0 && (
              <select defaultValue="" onChange={(e) => {
                const n = e.target.value;
                if (n && saved[n]) applyPreset(saved[n]);
                e.target.value = "";
              }} className="rounded border border-line bg-panel2 px-1.5 py-1 text-xs text-slate-300">
                <option value="">已存方案…</option>
                {Object.keys(saved).map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            )}
            {Object.keys(saved).length > 0 && (
              <select defaultValue="" onChange={(e) => {
                const n = e.target.value;
                if (n) {
                  const next = { ...saved };
                  delete next[n];
                  localStorage.setItem(SAVED_KEY, JSON.stringify(next));
                  setSaved(next);
                }
                e.target.value = "";
              }} className="rounded border border-line bg-panel2 px-1.5 py-1 text-xs text-slate-400">
                <option value="">删除方案…</option>
                {Object.keys(saved).map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            )}
          </div>

          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs sm:grid-cols-3 lg:grid-cols-4">
            {RANGE_DEFS.map((d) => (
              <div key={d.k} className="flex min-w-0 items-center gap-1">
                <span className="w-14 shrink-0 truncate text-slate-500">{d.label}{d.unit ?? ""}</span>
                {boundInput(d.k, "min")}{boundInput(d.k, "max")}
              </div>
            ))}
            {MOM_DEFS.map((d) => (
              <div key={d.k} className="flex min-w-0 items-center gap-1" title="动量需逐只取K线，候选限200只">
                <span className="w-14 shrink-0 truncate text-slate-500">{d.label}</span>
                {boundInput(d.k, "min")}{boundInput(d.k, "max")}
              </div>
            ))}
          </div>
          <p className="text-xs text-slate-500">动量筛选需逐只下载K线，候选股票超过 200 只会报错，请先收紧其他条件。</p>

          <div className="flex flex-wrap items-center gap-3 text-xs">
            {BOARDS.map((b) => (
              <label key={b.k} className="flex items-center gap-1 text-slate-300">
                <input type="checkbox" checked={form.boards.includes(b.k)}
                  onChange={(e) => setForm((f) => ({
                    ...f, boards: e.target.checked ? [...f.boards, b.k] : f.boards.filter((x) => x !== b.k),
                  }))} />
                {b.label}
              </label>
            ))}
            <span className="mx-1 h-4 w-px bg-line" />
            <label className="flex items-center gap-1 text-slate-300">
              <input type="checkbox" checked={form.exSt}
                onChange={(e) => setForm((f) => ({ ...f, exSt: e.target.checked }))} />
              剔除ST
            </label>
            <label className="flex items-center gap-1 text-slate-300">
              <input type="checkbox" checked={form.exSusp}
                onChange={(e) => setForm((f) => ({ ...f, exSusp: e.target.checked }))} />
              剔除停牌
            </label>
          </div>

          <details className="text-xs">
            <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
              行业筛选{form.inds.length ? `（已选 ${form.inds.length}）` : "（不限）"}
            </summary>
            <div className="mt-2">
              <input value={indQ} onChange={(e) => setIndQ(e.target.value)} placeholder="搜索行业…"
                className="mb-2 w-40 rounded border border-line bg-panel2 px-2 py-1 outline-none" />
              <div className="grid max-h-40 grid-cols-2 gap-y-1 overflow-y-auto sm:grid-cols-4 lg:grid-cols-6">
                {indShown.map((i) => (
                  <label key={i.name} className="flex items-center gap-1 text-slate-300">
                    <input type="checkbox" checked={form.inds.includes(i.name)}
                      onChange={(e) => setForm((f) => ({
                        ...f, inds: e.target.checked ? [...f.inds, i.name] : f.inds.filter((x) => x !== i.name),
                      }))} />
                    {i.name} <span className="text-slate-500">({i.count})</span>
                  </label>
                ))}
              </div>
            </div>
          </details>

          <button onClick={() => run()} disabled={loading}
            className="rounded bg-up px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50">
            {loading ? "筛选中…" : "开始筛选"}
          </button>
        </div>
      </Card>

      <Card title={
        res ? `结果 ${res.matched} / ${res.total_universe}${res.as_of ? ` · ${res.as_of.slice(0, 16).replace("T", " ")}` : ""}` : "结果"
      } extra={
        <div className="flex items-center gap-2">
          <a href={sel.size >= 2 && sel.size <= 50
              ? `#/backtest?mode=portfolio&codes=${[...sel].join(",")}&run=1` : undefined}
            className={`rounded border border-line px-2 py-0.5 text-xs ${
              sel.size >= 2 && sel.size <= 50
                ? "text-slate-300 hover:bg-panel2"
                : "pointer-events-none text-slate-600"}`}
            title={sel.size >= 2 && sel.size <= 50 ? "对选中股票运行组合回测" : "勾选 2–50 只股票"}>
            组合回测{sel.size ? `(${sel.size})` : ""}
          </a>
          <a href={sel.size >= 20 && sel.size <= 300
              ? `#/factor?codes=${[...sel].join(",")}` : undefined}
            className={`rounded border border-line px-2 py-0.5 text-xs ${
              sel.size >= 20 && sel.size <= 300
                ? "text-slate-300 hover:bg-panel2"
                : "pointer-events-none text-slate-600"}`}
            title={sel.size >= 20 && sel.size <= 300
              ? "对选中股票运行因子检验" : "勾选 20–300 只股票"}>
            因子检验
          </a>
          <button onClick={exportCsv} disabled={!res?.rows.length}
            className="rounded border border-line px-2 py-0.5 text-xs text-slate-300 hover:bg-panel2 disabled:opacity-40">
            导出 CSV
          </button>
        </div>
      }>
        {res?.notes.map((n) => <p key={n} className="mb-1 text-xs text-slate-500">{n}</p>)}
        <ErrorBanner error={err} onRetry={() => run()} />
        {loading && momPending && (
          <p className="mb-2 text-xs text-slate-400">动量需逐只计算K线，首次可能需 1–3 分钟，之后走本地缓存。</p>
        )}
        {loading && !res ? <Skeleton rows={8} /> : res ? (
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full whitespace-nowrap text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-slate-500">
                  <th className="px-2 py-1.5">
                    <input type="checkbox"
                      checked={sel.size > 0 && sel.size === res.rows.length}
                      onChange={(e) => setSel(e.target.checked ? new Set(res.rows.map((r) => r.code)) : new Set())} />
                  </th>
                  {COLS.map((c) => (
                    <th key={c.k} onClick={() => clickSort(c.k)}
                      className={`px-2 py-1.5 font-normal ${c.num ? "num" : ""} ${SORTABLE.has(c.k) ? "cursor-pointer hover:text-slate-300" : ""}`}>
                      {c.label}{sort.by === c.k ? (sort.desc ? " ↓" : " ↑") : ""}
                    </th>
                  ))}
                  {res.rows.some((r) => r.mom_20 != null || r.mom_60 != null) && (
                    <>
                      <th onClick={() => clickSort("mom_20")} className="num cursor-pointer px-2 py-1.5 font-normal hover:text-slate-300">
                        20日动量{sort.by === "mom_20" ? (sort.desc ? " ↓" : " ↑") : ""}</th>
                      <th onClick={() => clickSort("mom_60")} className="num cursor-pointer px-2 py-1.5 font-normal hover:text-slate-300">
                        60日动量{sort.by === "mom_60" ? (sort.desc ? " ↓" : " ↑") : ""}</th>
                    </>
                  )}
                  <th className="px-2 py-1.5 font-normal">操作</th>
                </tr>
              </thead>
              <tbody>
                {res.rows.map((r) => (
                  <tr key={r.code} className="border-b border-line/40">
                    <td className="px-2 py-1.5">
                      <input type="checkbox" checked={sel.has(r.code)}
                        onChange={(e) => setSel((s) => {
                          const n = new Set(s);
                          e.target.checked ? n.add(r.code) : n.delete(r.code);
                          return n;
                        })} />
                    </td>
                    {COLS.map((c) => (
                      <td key={c.k} className={`px-2 py-1.5 ${c.num ? "num" : ""}`}>{cell(c.k, r)}</td>
                    ))}
                    {(res.rows.some((x) => x.mom_20 != null || x.mom_60 != null)) && (
                      <>
                        <td className="num px-2 py-1.5">{cell("mom_20", r)}</td>
                        <td className="num px-2 py-1.5">{cell("mom_60", r)}</td>
                      </>
                    )}
                    <td className="px-2 py-1.5">
                      <button onClick={() => { if (addWatch(r.code)) toast("ok", `已加自选 ${r.code}`); }}
                        className="mr-2 text-xs text-slate-400 hover:text-up">加自选</button>
                      <Link to={`/backtest?code=${r.code}&run=1`} className="text-xs text-slate-400 hover:text-up">回测</Link>
                    </td>
                  </tr>
                ))}
                {!res.rows.length && (
                  <tr><td colSpan={COLS.length + 2} className="py-6 text-center text-sm text-slate-500">无匹配结果</td></tr>
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-slate-500">设置条件后点击「开始筛选」</p>
        )}
      </Card>
    </div>
  );
}
