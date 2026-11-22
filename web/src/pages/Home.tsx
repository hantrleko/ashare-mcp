import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type PaperStatus, type Quote } from "../api";
import { Card, ErrorBanner, PctText, Skeleton } from "../components/ui";
import { SearchBox } from "../components/SearchBox";
import { useAccount } from "../account";
import { fmtAmount, fmtNum, fmtPrice, fmtSigned } from "../format";

const DEFAULT_WATCH = ["600519", "000001", "300750", "601318", "000858"];
const WATCH_KEY = "ashare_watchlist";

function loadWatch(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(WATCH_KEY) || "null");
    if (Array.isArray(v) && v.every((s) => typeof s === "string")) return v;
  } catch { /* fall through */ }
  return DEFAULT_WATCH;
}

export default function Home() {
  const nav = useNavigate();
  const [indices, setIndices] = useState<Quote[]>([]);
  const [idxErr, setIdxErr] = useState<unknown>(null);
  const [watch, setWatch] = useState<string[]>(loadWatch);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [status, setStatus] = useState<PaperStatus | null>(null);
  const [ov, setOv] = useState<Record<string, unknown> | null>(null);
  const [ovLoading, setOvLoading] = useState(false);
  const [ovErr, setOvErr] = useState<unknown>(null);
  const [ovSrc, setOvSrc] = useState("");

  const loadIndices = useCallback(async () => {
    try {
      const r = await api.indices();
      setIndices(r.data);
      setIdxErr(null);
    } catch (e) { setIdxErr(e); }
  }, []);

  const fetchWatch = useCallback(async (syms: string[]) => {
    if (!syms.length) { setQuotes([]); return; }
    try {
      const r = await api.quotes(syms);
      setQuotes(r.data);
    } catch { /* keep stale */ }
  }, []);

  const { account } = useAccount();
  const loadStatus = useCallback(async () => {
    try { setStatus(await api.paperStatus(account)); } catch { /* offline ok */ }
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

  const breadth = (ov?.breadth ?? {}) as Record<string, unknown>;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-9">
        {indices.length === 0 && !idxErr && <div className="col-span-full"><Skeleton rows={2} /></div>}
        {indices.map((q) => (
          <div key={q.symbol} className="rounded-lg border border-line bg-panel px-3 py-2">
            <div className="truncate text-xs text-slate-400">{q.name}</div>
            <div className="num text-sm font-medium">{fmtPrice(q.price)}</div>
            <PctText v={q.pct_chg} className="text-xs" />
          </div>
        ))}
      </div>
      <ErrorBanner error={idxErr} onRetry={loadIndices} />

      <div className="grid gap-5 lg:grid-cols-3">
        <Card
          title="自选股"
          className="lg:col-span-2"
          extra={
            <SearchBox
              className="w-52"
              onPick={(h) => {
                if (!watch.includes(h.code)) setWatch([...watch, h.code]);
                nav(`/stock/${h.code}`);
              }}
            />
          }
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-slate-500">
                <th className="py-1.5 font-normal">名称</th>
                <th className="font-normal">代码</th>
                <th className="text-right font-normal">最新</th>
                <th className="text-right font-normal">涨跌幅</th>
                <th className="hidden text-right font-normal sm:table-cell">成交额</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {quotes.map((q) => {
                const code = q.code || q.symbol || "";
                return (
                  <tr
                    key={code}
                    onClick={() => nav(`/stock/${code}`)}
                    className="cursor-pointer border-b border-line/50 hover:bg-panel2"
                  >
                    <td className="py-2">{q.name || code}</td>
                    <td className="num text-slate-400">{code}</td>
                    <td className="num text-right">{fmtPrice(q.price)}</td>
                    <td className="text-right"><PctText v={q.pct_chg} /></td>
                    <td className="num hidden text-right text-slate-400 sm:table-cell">
                      {fmtAmount(q.amount)}
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
                <tr><td colSpan={6} className="py-6 text-center text-slate-500">自选股为空，右上角搜索添加</td></tr>
              )}
            </tbody>
          </table>
        </Card>

        <div className="space-y-5">
          <Card title="模拟账户" extra={<Link to="/paper" className="text-xs text-slate-400 hover:text-slate-200">进入 →</Link>}>
            {status ? (
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-400">总资产</span>
                  <span className="num font-medium">{fmtNum(status.equity)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">总盈亏</span>
                  <span className={`num ${status.total_pnl >= 0 ? "text-up" : "text-down"}`}>
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
                  全市场快照（涨跌家数 / 成交额），抓取约1-2分钟。
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
              <div className="grid grid-cols-2 gap-2 text-sm">
                <Stat label="上涨" v={String(breadth.advance ?? "—")} cls="text-up" />
                <Stat label="下跌" v={String(breadth.decline ?? "—")} cls="text-down" />
                <Stat label="平盘" v={String(breadth.flat ?? "—")} />
                <Stat label="平均涨跌幅" v={`${breadth.avg_pct_chg ?? "—"}%`} />
                <div className="col-span-2 flex justify-between border-t border-line pt-2">
                  <span className="text-slate-400">两市成交额</span>
                  <span className="num">{String(breadth.total_amount_yi ?? "—")}亿</span>
                </div>
                {ovSrc && <div className="col-span-2 text-xs text-slate-500">数据源 {ovSrc}</div>}
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
