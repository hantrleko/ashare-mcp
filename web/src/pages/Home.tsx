import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowDown, ArrowRight, ArrowUp, ArrowLeftRight, ChartColumn,
  FlaskConical, ListPlus, ScanSearch, Trophy, X,
  type LucideIcon,
} from "lucide-react";
import { api, type EquityPoint, type OverviewData, type PaperStatus, type Quote } from "../api";
import { Card, ErrorBanner, PctText, Skeleton } from "../components/ui";
import { SearchBox } from "../components/SearchBox";
import { Sparkline } from "../components/Sparkline";
import { PriceFlash, useSparklines } from "../components/liveness";
import { useAccount } from "../account";
import { fmtAmount, fmtNum, fmtPrice, fmtSigned, signedClass } from "../format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Skeleton as Sk } from "@/components/ui/skeleton";
import { CategoryBar } from "@/components/tremor/CategoryBar";

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

const QUICK: { to: string; label: string; desc: string; icon: LucideIcon }[] = [
  { to: "/screener", label: "选股", desc: "估值·市值·动量条件筛选", icon: ScanSearch },
  { to: "/backtest", label: "回测", desc: "单股与组合策略检验", icon: ArrowLeftRight },
  { to: "/factor", label: "因子研究", desc: "IC·分位组合·多空", icon: FlaskConical },
  { to: "/arena", label: "AI 竞技场", desc: "Agent 模拟盘排行", icon: Trophy },
];

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
    <TableHead
      onClick={k ? () => setSort((s) => ({
        key: k, dir: s.key === k ? ((s.dir * -1) as 1 | -1) : -1,
      })) : undefined}
      className={`${cls} ${k ? "cursor-pointer select-none hover:text-foreground" : ""}`}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        {k && sort.key === k && (
          sort.dir === -1
            ? <ArrowDown className="size-3 text-accent" />
            : <ArrowUp className="size-3 text-accent" />
        )}
      </span>
    </TableHead>
  );

  const big = indices.slice(0, 4);
  const small = indices.slice(4);

  return (
    <div className="space-y-5">
      {indices.length === 0 && !idxErr && <Skeleton rows={2} />}

      {/* headline index KPI cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {big.map((q) => {
          const sym = q.symbol || "";
          const sp = idxData.get(sym);
          return (
            <div key={sym}
                 className="rounded-xl border border-border bg-card p-4 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm text-muted-foreground">
                  {q.name}</span>
                <Badge variant={
                  q.pct_chg == null ? "secondary"
                    : q.pct_chg > 0 ? "up" : q.pct_chg < 0 ? "down" : "secondary"}>
                  {q.pct_chg != null
                    ? `${q.pct_chg >= 0 ? "+" : ""}${Number(q.pct_chg).toFixed(2)}%`
                    : "—"}
                </Badge>
              </div>
              <div className="num mt-1 text-xl font-semibold tracking-tight">
                <PriceFlash value={q.price}>{fmtPrice(q.price)}</PriceFlash>
              </div>
              <div className="mt-0.5 flex items-center justify-between gap-2">
                <span className={`num text-xs ${signedClass(q.change)}`}>
                  {q.change != null ? fmtSigned(q.change, 2) : ""}
                </span>
                {sp && (
                  <Sparkline prices={sp.points.map((p) => p.price)}
                             prevClose={sp.prev_close}
                             width={110} height={28} id={sym} />
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* remaining indices: compact row (scrolls horizontally on mobile) */}
      {small.length > 0 && (
        <div className="-mx-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
          <div className="flex min-w-max gap-3 sm:min-w-0">
            {small.map((q) => {
              const sym = q.symbol || "";
              const sp = idxData.get(sym);
              return (
                <div key={sym}
                     className="w-40 rounded-xl border border-border bg-card px-3 py-2.5 shadow-sm sm:w-auto sm:min-w-0 sm:flex-1">
                  <div className="truncate text-xs text-muted-foreground">
                    {q.name}</div>
                  <div className="num mt-0.5 text-sm font-medium">
                    <PriceFlash value={q.price}>{fmtPrice(q.price)}</PriceFlash>
                  </div>
                  <div className="mt-0.5 flex items-center justify-between gap-1">
                    <span className={`num text-xs ${signedClass(q.pct_chg)}`}>
                      {q.pct_chg != null
                        ? `${q.pct_chg >= 0 ? "+" : ""}${Number(q.pct_chg).toFixed(2)}%`
                        : ""}
                    </span>
                    {sp && <Sparkline prices={sp.points.map((p) => p.price)}
                                      prevClose={sp.prev_close}
                                      width={56} height={18} id={sym} />}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <ErrorBanner error={idxErr} onRetry={loadIndices} />

      {/* quick entries */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {QUICK.map((e) => (
          <Link key={e.to} to={e.to}
                className="group flex items-center gap-3 rounded-xl border border-border bg-card p-3.5 shadow-sm transition-colors hover:border-accent/60 hover:bg-muted/40">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent transition-colors group-hover:bg-accent/15">
              <e.icon className="size-4.5" />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium text-foreground">
                {e.label}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {e.desc}</span>
            </span>
          </Link>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card
          title="自选股"
          className="min-w-0 lg:col-span-2"
          extra={
            <div className="flex items-center gap-3">
              {updatedAt && <span className="text-xs text-muted-foreground">更新于 {updatedAt}</span>}
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
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>名称</TableHead>
                {th("最新", "price", "text-right")}
                {th("涨跌幅", "pct_chg", "text-right")}
                <TableHead className="hidden sm:table-cell">走势</TableHead>
                {th("成交额", "amount", "hidden text-right sm:table-cell")}
                {th("换手", "turnover", "hidden text-right md:table-cell")}
                <TableHead className="hidden text-right lg:table-cell">总市值</TableHead>
                <TableHead className="w-8" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((q) => {
                const code = q.code || q.symbol || "";
                const sp = watchData.get(code);
                return (
                  <TableRow
                    key={code}
                    onClick={() => nav(`/stock/${code}`)}
                    className="group cursor-pointer hover:bg-muted/50"
                  >
                    <TableCell className="py-2.5">
                      <div className="font-medium text-foreground">
                        {(q.name || code).replace(/\s+/g, "")}</div>
                      <div className="num text-xs text-muted-foreground">{code}</div>
                    </TableCell>
                    <TableCell className="num text-right">
                      <PriceFlash value={q.price}>{fmtPrice(q.price)}</PriceFlash>
                    </TableCell>
                    <TableCell className="text-right">
                      <Badge variant={
                        q.pct_chg == null ? "secondary"
                          : q.pct_chg > 0 ? "up"
                          : q.pct_chg < 0 ? "down" : "secondary"}>
                        <PctText v={q.pct_chg} className="text-inherit" />
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      {sp && <Sparkline prices={sp.points.map((p) => p.price)}
                                        prevClose={sp.prev_close} width={72} height={20} id={code} />}
                    </TableCell>
                    <TableCell className="num hidden text-right text-muted-foreground sm:table-cell">
                      {fmtAmount(q.amount)}
                    </TableCell>
                    <TableCell className="num hidden text-right text-muted-foreground md:table-cell">
                      {q.turnover != null ? `${Number(q.turnover).toFixed(2)}%` : "—"}
                    </TableCell>
                    <TableCell className="num hidden text-right text-muted-foreground lg:table-cell">
                      {fmtAmount(q.mkt_cap)}
                    </TableCell>
                    <TableCell>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setWatch(watch.filter((s) => s !== code));
                        }}
                        className="inline-flex size-6 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-up/15 hover:text-up max-sm:opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
                        title="移除"
                        aria-label={`移除 ${q.name || code}`}
                      >
                        <X className="size-3.5" />
                      </button>
                    </TableCell>
                  </TableRow>
                );
              })}
              {quotes.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="py-8 text-center">
                    {watchLoaded ? (
                      <span className="inline-flex flex-col items-center gap-2 text-muted-foreground">
                        <ListPlus className="size-6" />
                        自选股为空，右上角搜索添加
                      </span>
                    ) : (
                      <Skeleton rows={3} />
                    )}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Card>

        <div className="min-w-0 space-y-5">
          <Card
            title={`模拟账户 · ${acctName}`}
            extra={
              <Link to="/paper"
                    className="inline-flex items-center gap-0.5 text-xs text-muted-foreground transition-colors hover:text-foreground">
                进入 <ArrowRight className="size-3.5" />
              </Link>
            }
          >
            {status ? (
              <div className="space-y-3">
                <div className="flex items-end justify-between gap-2">
                  <div>
                    <div className="text-xs text-muted-foreground">总资产</div>
                    <div className="num text-2xl font-semibold tracking-tight">
                      {fmtNum(status.equity)}</div>
                  </div>
                  {hist.length >= 2 && (
                    <Sparkline prices={hist.map((p) => p.equity)}
                               width={110} height={34} id="acct" />
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="rounded-lg bg-muted/50 px-2.5 py-2">
                    <div className="text-xs text-muted-foreground">当日盈亏</div>
                    <div className={`num mt-0.5 text-sm ${signedClass(dayPnl)}`}>
                      {dayPnl != null ? fmtSigned(dayPnl) : "—"}
                    </div>
                  </div>
                  <div className="rounded-lg bg-muted/50 px-2.5 py-2">
                    <div className="text-xs text-muted-foreground">总盈亏</div>
                    <div className={`num mt-0.5 text-sm ${signedClass(status.total_pnl)}`}>
                      {fmtSigned(status.total_pnl)}
                    </div>
                  </div>
                  <div className="rounded-lg bg-muted/50 px-2.5 py-2">
                    <div className="text-xs text-muted-foreground">收益率</div>
                    <div className="mt-0.5 text-sm">
                      <PctText v={status.total_return_pct} />
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">账户信息暂不可用</p>
            )}
          </Card>

          <Card title="市场广度">
            {!ov && !ovLoading && (
              <div className="space-y-3">
                <p className="text-xs leading-5 text-muted-foreground">
                  全市场快照（涨跌家数 / 成交额 / 涨跌幅分布），抓取约1-2分钟。
                </p>
                <Button variant="secondary" size="sm" onClick={loadOverview}>
                  <ChartColumn className="size-4" />
                  加载市场广度
                </Button>
              </div>
            )}
            {ovLoading && (
              <div className="space-y-2 py-2">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="inline-block size-3.5 animate-spin rounded-full border-2 border-slate-500 border-t-transparent" />
                  正在爬取全市场快照，约需1-2分钟…
                </div>
                <Sk className="h-2 w-full rounded-full" />
                <Sk className="h-20 w-full" />
                <Sk className="h-24 w-full" />
              </div>
            )}
            <ErrorBanner error={ovErr} onRetry={loadOverview} />
            {ov && (
              <div className="space-y-3">
                <CategoryBar
                  values={[
                    { name: "上涨", value: Number(breadth.advance ?? 0), color: "var(--color-up)" },
                    { name: "平盘", value: Number(breadth.flat ?? 0), color: "var(--color-slate-500)" },
                    { name: "下跌", value: Number(breadth.decline ?? 0), color: "var(--color-down)" },
                  ]}
                />
                <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                  <Stat label="涨停" v={String(breadth.limit_up ?? "—")} cls="text-up" />
                  <Stat label="跌停" v={String(breadth.limit_down ?? "—")} cls="text-down" />
                  <Stat label="平盘" v={String(breadth.flat ?? "—")} />
                  <Stat label="平均涨跌幅" v={`${breadth.avg_pct_chg ?? "—"}%`} />
                  <div className="col-span-2 flex justify-between border-t border-border pt-2">
                    <span className="text-muted-foreground">两市成交额</span>
                    <span className="num">{String(breadth.total_amount_yi ?? "—")}亿</span>
                  </div>
                </div>
                {breadth.distribution && <BreadthChart dist={breadth.distribution} />}
                {ovSrc && <div className="text-xs text-muted-foreground">数据源 {ovSrc}</div>}
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
      <span className="text-muted-foreground">{label}</span>
      <span className={`num ${cls}`}>{v}</span>
    </div>
  );
}

function BreadthChart({ dist }: { dist: { range: string; count: number }[] }) {
  const max = Math.max(...dist.map((d) => d.count), 1);
  return (
    <svg viewBox={`0 0 ${dist.length * 24} 120`} className="h-32 w-full">
      {dist.map((d, i) => {
        const h = (d.count / max) * 88;
        const isUp = i > 6;
        const color = i === 6 ? "var(--color-slate-500)"
          : isUp ? "var(--color-up)" : "var(--color-down)";
        return (
          <g key={d.range}>
            <rect x={i * 24 + 3} y={92 - h} width={18} height={h}
                  fill={color} opacity={0.85} rx={2} />
            <text x={i * 24 + 12} y={88 - h} textAnchor="middle"
                  fontSize="7" fill="var(--color-chart-text)" className="num">
              {d.count > 0 ? d.count : ""}
            </text>
            <text x={i * 24 + 12} y={112} textAnchor="middle"
                  fontSize="6.5" fill="var(--color-slate-500)">
              {d.range}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
