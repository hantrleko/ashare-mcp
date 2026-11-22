import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type EquityPoint, type OverviewData, type PaperStatus, type Quote } from "../api";
import { Card, ErrorBanner, PctText, Skeleton } from "../components/ui";
import { SearchBox } from "../components/SearchBox";
import { Sparkline } from "../components/Sparkline";
import { PriceFlash, useSparklines } from "../components/liveness";
import { useAccount } from "../account";
import { fmtAmount, fmtNum, fmtPrice, fmtSigned, signedClass } from "../format";

const DEFAULT_WATCH = ["600519", "000001", "300750", "601318", "000858"];
const WATCH_KEY = "ashare_watchlist";
const SORT_KEY = "ashare_watch_sort";
const INDEX_SYMS = [
  "sh000001", "sz399001", "sz399006", "sh000300", "sh000688",
  "sh000016", "sh000905", "sh000852", "bj899050",
];

type SortKey = "pct_chg" | "price" | "amount" | "turnover";

function loadWatch(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(WATCH_KEY) || "null");
    if (Array.isArray(v) && v.every((s) => typeof s === "string")) return v;
  } catch { /* fall through */ }
  return DEFAULT_WATCH;
}

function loadSort(): { key: SortKey; dir: 1 | -1 } {
  try {
    const v = JSON.parse(localStorage.getItem(SORT_KEY) || "null");
    if (v && ["pct_chg", "price", "amount", "turnover"].includes(v.key)
        && (v.dir === 1 || v.dir === -1)) return v;
  } catch { /* fall through */ }
  return { key: "pct_chg", dir: -1 };
}

export default function Home() {
  const nav = useNavigate();
  const [indices, setIndices] = useState<Quote[]>([]);
  const [idxErr, setIdxErr] = useState<unknown>(null);
  const [watch, setWatch] = useState<string[]>(loadWatch);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [status, setStatus] = useState<PaperStatus | null>(null);
  const [hist, setHist] = useState<EquityPoint[]>([]);
  const [ov, setOv] = useState<OverviewData | null>(null);
  const [ovLoading, setOvLoading] = useState(false);
  const [ovErr, setOvErr] = useState<unknown>(null);
  const [ovSrc, setOvSrc] = useState("");
  const [sort, setSort] = useState(loadSort);
  const [updatedAt, setUpdatedAt] = useState<string>("");
  const [watchLoaded, setWatchLoaded] = useState(false);

  const idxData = useSparklines(INDEX_SYMS);
  const watchData = useSparklines(watch);

  const loadIndices = useCallback(async () => {
    try {
      const r = await api.indices();
      setIndices(r.data);
      setIdxErr(null);
      setUpdatedAt(new Date().toTimeString().slice(0, 8));
    } catch (e) { setIdxErr(e); }
  }, []);

  const fetchWatch = useCallback(async (syms: string[]) => {
    if (!syms.length) { setQuotes([]); setWatchLoaded(true); return; }
    try {
      const r = await api.quotes(syms);
      setQuotes(r.data);
      setUpdatedAt(new Date().toTimeString().slice(0, 8));
    } catch { /* keep stale */ }
    finally { setWatchLoaded(true); }
  }, []);

  const { account, accounts } = useAccount();
  const loadStatus = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        api.paperStatus(account), api.paperHistory(account)]);
      setStatus(s);
      setHist(h.data);
    } catch { /* offline ok */ }
  }, [account]);

  useEffect(() => {
    loadIndices();
    loadStatus();
    const t = setInterval(() => { loadIndices(); loadStatus(); }, 30_000);
    return () => clearInterval(t);
  }, [loadIndices, loadStatus]);

  useEffect(() => {
    localStorage.setItem(WATCH_KEY, JSON.stringify(watch));
    fetchWatch(watch);
    const t = setInterval(() => fetchWatch(watch), 30_000);
    return () => clearInterval(t);
  }, [watch, fetchWatch]);

  useEffect(() => {
    localStorage.setItem(SORT_KEY, JSON.stringify(sort));
  }, [sort]);

  const loadOverview = async () => {
    setOvLoading(true);
    setOvErr(null);
    try {
      const r = await api.overview();
      setOv(r.data);
      setOvSrc(r.source || "");
    } catch (e) { setOvErr(e); }
    finally { setOvLoading(false); }
  };

  const breadth = ov?.breadth ?? {};
  const acctName = accounts.find((a) => a.id === account)?.name ?? account;
  const dayPnl = status && hist.length >= 2
    ? status.equity - hist[hist.length - 2].equity : null;

  const sorted = useMemo(() => {
    const arr = [...quotes];
    arr.sort((a, b) => {
      const va = Number(a[sort.key] ?? -Infinity);
      const vb = Number(b[sort.key] ?? -Infinity);
      return (va - vb) * sort.dir;
    });
    return arr;
  }, [quotes, sort]);

  const th = (label: string, k: SortKey | null, cls = "") => (
    <th
      onClick={k ? () => setSort((s) => ({
        key: k, dir: s.key === k ? ((s.dir * -1) as 1 | -1) : -1,
      })) : undefined}
      className={`${cls} ${k ? "cursor-pointer select-none hover:text-slate-300" : ""}`}
    >
      {label}{k && sort.key === k && (sort.dir === -1 ? " ↓" : " ↑")}
    </th>
  );

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-9">
        {indices.length === 0 && !idxErr && <div className="col-span-full"><Skeleton rows={2} /></div>}
        {indices.map((q) => {
          const sym = q.symbol || "";
          const sp = idxData.get(sym);
          return (
            <div key={sym} className="rounded-lg border border-line bg-panel px-3 py-2">
              <div className="flex items-baseline justify-between">
                <div className="truncate text-xs text-slate-400">{q.name}</div>
              </div>
              <div className="num text-sm font-medium">
                <PriceFlash value={q.price}>{fmtPrice(q.price)}</PriceFlash>
              </div>
              <div className="flex items-center justify-between gap-1">
                <span className="num text-xs">
                  <span className={signedClass(q.change)}>
                    {q.change != null ? fmtSigned(q.change, 2) : ""}
                  </span>
                  <PctText v={q.pct_chg} className="ml-1" />
                </span>
                {sp && <Sparkline prices={sp.points.map((p) => p.price)}
                                  prevClose={sp.prev_close} width={64} height={20} id={sym} />}
              </div>
            </div>
          );
        })}
      </div>
      <ErrorBanner error={idxErr} onRetry={loadIndices} />

      <div className="grid gap-5 lg:grid-cols-3">
        <Card
          title="自选股"
          className="min-w-0 lg:col-span-2"
          extra={
            <div className="flex items-center gap-3">
              {updatedAt && <span className="text-xs text-slate-500">更新于 {updatedAt}</span>}
              <SearchBox
                className="hidden w-52 sm:block"
                onPick={(h) => {
                  if (!watch.includes(h.code)) setWatch([...watch, h.code]);
                  nav(`/stock/${h.code}`);
                }}
              />
            </div>
          }
        >
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-slate-500">
                <th className="py-1.5 font-normal">名称</th>
                <th className="font-normal">代码</th>
                {th("最新", "price", "text-right font-normal")}
                {th("涨跌幅", "pct_chg", "text-right font-normal")}
                <th className="hidden font-normal sm:table-cell">走势</th>
                {th("成交额", "amount", "hidden text-right font-normal sm:table-cell")}
                {th("换手", "turnover", "hidden text-right font-normal md:table-cell")}
                {th("总市值", null, "hidden text-right font-normal lg:table-cell")}
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((q) => {
                const code = q.code || q.symbol || "";
                const sp = watchData.get(code);
                return (
                  <tr
                    key={code}
                    onClick={() => nav(`/stock/${code}`)}
                    className="cursor-pointer border-b border-line/50 hover:bg-panel2"
                  >
                    <td className="py-2">{q.name || code}</td>
                    <td className="num text-slate-400">{code}</td>
                    <td className="num text-right">
                      <PriceFlash value={q.price}>{fmtPrice(q.price)}</PriceFlash>
                    </td>
                    <td className="text-right"><PctText v={q.pct_chg} /></td>
                    <td className="hidden sm:table-cell">
                      {sp && <Sparkline prices={sp.points.map((p) => p.price)}
                                        prevClose={sp.prev_close} width={72} height={20} id={code} />}
                    </td>
                    <td className="num hidden text-right text-slate-400 sm:table-cell">
                      {fmtAmount(q.amount)}
                    </td>
                    <td className="num hidden text-right text-slate-400 md:table-cell">
                      {q.turnover != null ? `${Number(q.turnover).toFixed(2)}%` : "—"}
                    </td>
                    <td className="num hidden text-right text-slate-400 lg:table-cell">
                      {fmtAmount(q.mkt_cap)}
                    </td>
                    <td>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setWatch(watch.filter((s) => s !== code));
                        }}
                        className="rounded px-1.5 text-slate-500 hover:bg-red-950/50 hover:text-red-400"
                        title="移除"
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                );
              })}
              {quotes.length === 0 && (
                <tr><td colSpan={9} className="py-6 text-center text-slate-500">
                  {watchLoaded ? "自选股为空，右上角搜索添加" : <Skeleton rows={3} />}
                </td></tr>
              )}
            </tbody>
          </table>
          </div>
        </Card>

        <div className="min-w-0 space-y-5">
          <Card
            title={`模拟账户 · ${acctName}`}
            extra={<Link to="/paper" className="text-xs text-slate-400 hover:text-slate-200">进入 →</Link>}
          >
            {status ? (
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs text-slate-500">总资产</div>
                    <div className="num font-medium">{fmtNum(status.equity)}</div>
                  </div>
                  {hist.length >= 2 && (
                    <Sparkline prices={hist.map((p) => p.equity)} width={96} height={30} id="acct" />
                  )}
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">当日盈亏</span>
                  <span className={`num ${signedClass(dayPnl)}`}>
                    {dayPnl != null ? fmtSigned(dayPnl) : "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">总盈亏</span>
                  <span className={`num ${signedClass(status.total_pnl)}`}>
                    {fmtSigned(status.total_pnl)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">收益率</span>
                  <PctText v={status.total_return_pct} />
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-500">账户信息暂不可用</p>
            )}
          </Card>

          <Card title="市场广度">
            {!ov && !ovLoading && (
              <div className="space-y-2">
                <p className="text-xs text-slate-500">
                  全市场快照（涨跌家数 / 成交额 / 涨跌幅分布），抓取约1-2分钟。
                </p>
                <button
                  onClick={loadOverview}
                  className="rounded border border-line bg-panel2 px-3 py-1.5 text-sm hover:border-slate-500"
                >
                  加载市场广度
                </button>
              </div>
            )}
            {ovLoading && (
              <div className="py-4 text-center text-sm text-slate-400">
                <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-500 border-t-transparent align-middle" />
                正在爬取全市场快照，约需1-2分钟…
              </div>
            )}
            <ErrorBanner error={ovErr} onRetry={loadOverview} />
            {ov && (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <Stat label="上涨" v={String(breadth.advance ?? "—")} cls="text-up" />
                  <Stat label="下跌" v={String(breadth.decline ?? "—")} cls="text-down" />
                  <Stat label="涨停" v={String(breadth.limit_up ?? "—")} cls="text-up" />
                  <Stat label="跌停" v={String(breadth.limit_down ?? "—")} cls="text-down" />
                  <Stat label="平盘" v={String(breadth.flat ?? "—")} />
                  <Stat label="平均涨跌幅" v={`${breadth.avg_pct_chg ?? "—"}%`} />
                  <div className="col-span-2 flex justify-between border-t border-line pt-2">
                    <span className="text-slate-400">两市成交额</span>
                    <span className="num">{String(breadth.total_amount_yi ?? "—")}亿</span>
                  </div>
                </div>
                {breadth.distribution && <BreadthChart dist={breadth.distribution} />}
                {ovSrc && <div className="text-xs text-slate-500">数据源 {ovSrc}</div>}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, v, cls = "" }: { label: string; v: string; cls?: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-slate-400">{label}</span>
      <span className={`num ${cls}`}>{v}</span>
    </div>
  );
}

const UP_C = "#ef5350";
const DOWN_C = "#26a69a";

function BreadthChart({ dist }: { dist: { range: string; count: number }[] }) {
  const max = Math.max(...dist.map((d) => d.count), 1);
  return (
    <svg viewBox={`0 0 ${dist.length * 24} 120`} className="h-32 w-full">
      {dist.map((d, i) => {
        const h = (d.count / max) * 88;
        const isUp = i > 6;
        const color = i === 6 ? "#64748b" : isUp ? UP_C : DOWN_C;
        return (
          <g key={d.range}>
            <rect x={i * 24 + 3} y={92 - h} width={18} height={h}
                  fill={color} opacity={0.8} rx={1} />
            <text x={i * 24 + 12} y={88 - h} textAnchor="middle"
                  fontSize="7" fill="#94a3b8" className="num">
              {d.count > 0 ? d.count : ""}
            </text>
            <text x={i * 24 + 12} y={112} textAnchor="middle"
                  fontSize="6.5" fill="#64748b">
              {d.range}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
