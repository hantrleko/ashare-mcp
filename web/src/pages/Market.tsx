import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Card, ErrorBanner, Spinner } from "../components/ui";
import { pctClass, todayYmd } from "../format";

const POOLS: [string, string][] = [
  ["zt", "涨停"], ["dt", "跌停"], ["zb", "炸板"], ["strong", "强势股"],
  ["prev", "昨涨停今表现"], ["new", "次新股"],
];
const KINDS: [string, string][] = [
  ["yjbb", "业绩报表"], ["yjyg", "业绩预告"], ["yysj", "业绩快报"],
];

export default function Market() {
  return (
    <div className="space-y-5">
      <LimitPoolCard />
      <EarningsCard />
      <AnnouncementsCard />
    </div>
  );
}

function GenericTable({ rows }: { rows: Record<string, unknown>[] }) {
  const cols = useMemo(() => (rows.length ? Object.keys(rows[0]) : []), [rows]);
  if (!rows.length) return <p className="py-4 text-center text-sm text-slate-500">暂无数据</p>;
  return (
    <div className="max-h-[28rem] overflow-auto">
      <table className="w-full whitespace-nowrap text-xs">
        <thead className="sticky top-0 bg-panel">
          <tr className="border-b border-line text-left text-slate-500">
            {cols.map((c) => <th key={c} className="px-2 py-1.5 font-normal">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line/40 hover:bg-panel2">
              {cols.map((c) => {
                const v = r[c];
                const num = typeof v === "number";
                const isPct = num && (c.includes("%") || c.includes("幅") || c.includes("比"));
                return (
                  <td key={c} className={`num px-2 py-1.5 ${isPct ? pctClass(v as number) : ""}`}>
                    {v == null ? "—" : num ? v.toLocaleString("zh-CN", { maximumFractionDigits: 4 }) : String(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LimitPoolCard() {
  const [pool, setPool] = useState("zt");
  const [date, setDate] = useState("");
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null);
  const [src, setSrc] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await api.limitPool(pool, date.trim());
      setRows(r.data);
      setSrc(r.source || "");
      setErr(null);
    } catch (e) { setErr(e); }
    finally { setBusy(false); }
  }, [pool, date]);

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Card
      title="涨跌停池"
      extra={<span className="text-xs text-slate-500">该接口只覆盖近30个交易日</span>}
    >
      <div className="mb-3 flex flex-wrap items-end gap-2 text-sm">
        <div className="flex overflow-hidden rounded border border-line">
          {POOLS.map(([v, l]) => (
            <button key={v} onClick={() => setPool(v)}
              className={`px-2.5 py-1.5 ${v === pool ? "bg-panel2 text-slate-100" : "text-slate-400"}`}>{l}</button>
          ))}
        </div>
        <input value={date} onChange={(e) => setDate(e.target.value)} placeholder={`交易日 留空=今天 ${todayYmd()}`}
          className="num w-56 rounded border border-line bg-panel2 px-2 py-1.5 outline-none placeholder:text-slate-600" />
        <button onClick={load} disabled={busy}
          className="rounded bg-slate-700 px-3 py-1.5 hover:bg-slate-600 disabled:opacity-40">查询</button>
      </div>
      {busy ? <Spinner /> : (
        <>
          <ErrorBanner error={err} onRetry={load} />
          {rows && <GenericTable rows={rows} />}
          {rows && <p className="mt-2 text-xs text-slate-500">{rows.length} 条 · 数据源 {src}</p>}
        </>
      )}
    </Card>
  );
}

function EarningsCard() {
  const [rpt, setRpt] = useState("20250930");
  const [kind, setKind] = useState("yjbb");
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null);
  const [src, setSrc] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      const r = await api.earnings(rpt.trim(), kind);
      setRows(r.data);
      setSrc(r.source || "");
      setErr(null);
    } catch (e) { setErr(e); }
    finally { setBusy(false); }
  };

  return (
    <Card title="业绩日历" extra={<span className="text-xs text-slate-500">按报告期查全市场披露，首次爬取30–60秒</span>}>
      <div className="mb-3 flex flex-wrap items-end gap-2 text-sm">
        <input value={rpt} onChange={(e) => setRpt(e.target.value)} placeholder="报告期 YYYYMMDD"
          className="num w-40 rounded border border-line bg-panel2 px-2 py-1.5 outline-none" />
        <select value={kind} onChange={(e) => setKind(e.target.value)}
          className="rounded border border-line bg-panel2 px-2 py-1.5">
          {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <button onClick={load} disabled={busy}
          className="rounded bg-slate-700 px-3 py-1.5 hover:bg-slate-600 disabled:opacity-40">加载</button>
        {busy && <span className="text-xs text-slate-500">首次加载较慢，请稍候…</span>}
      </div>
      {busy ? <Spinner label="爬取全市场业绩数据…" /> : (
        <>
          <ErrorBanner error={err} onRetry={load} />
          {rows && <GenericTable rows={rows} />}
          {rows && <p className="mt-2 text-xs text-slate-500">{rows.length} 条 · 数据源 {src}</p>}
        </>
      )}
    </Card>
  );
}

function AnnouncementsCard() {
  const [date, setDate] = useState("");
  const [filter, setFilter] = useState("");
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null);
  const [src, setSrc] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      const r = await api.announcements("", date.trim());
      setRows(r.data);
      setSrc(r.source || "");
      setErr(null);
    } catch (e) { setErr(e); }
    finally { setBusy(false); }
  };

  const filtered = useMemo(() => {
    if (!rows) return null;
    const f = filter.trim();
    if (!f) return rows;
    return rows.filter((r) =>
      Object.values(r).some((v) => String(v ?? "").includes(f)));
  }, [rows, filter]);

  return (
    <Card title="当日公告" extra={<span className="text-xs text-slate-500">全市场公告列表</span>}>
      <div className="mb-3 flex flex-wrap items-end gap-2 text-sm">
        <input value={date} onChange={(e) => setDate(e.target.value)} placeholder={`日期 留空=今天 ${todayYmd()}`}
          className="num w-56 rounded border border-line bg-panel2 px-2 py-1.5 outline-none placeholder:text-slate-600" />
        <button onClick={load} disabled={busy}
          className="rounded bg-slate-700 px-3 py-1.5 hover:bg-slate-600 disabled:opacity-40">查询</button>
        {rows && (
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="筛选（代码/名称/标题）"
            className="w-56 rounded border border-line bg-panel2 px-2 py-1.5 outline-none placeholder:text-slate-600" />
        )}
      </div>
      {busy ? <Spinner /> : (
        <>
          <ErrorBanner error={err} onRetry={load} />
          {filtered && <GenericTable rows={filtered} />}
          {filtered && <p className="mt-2 text-xs text-slate-500">{filtered.length} 条 · 数据源 {src}</p>}
        </>
      )}
    </Card>
  );
}
