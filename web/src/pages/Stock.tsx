import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  CandlestickSeries, HistogramSeries, LineSeries,
  createSeriesMarkers,
  type ISeriesApi, type MouseEventParams,
} from "lightweight-charts";
import { api, type Bar, type Order, type Quote } from "../api";
import { boll, macd, rsi, sma, toPts } from "../indicators";
import { Card, EmptyState, ErrorBanner, PctText, Skeleton, Spinner } from "../components/ui";
import { useChart } from "../components/chart";
import { DOWN, UP, fmtAmount, fmtPct, fmtPrice, fmtSigned, todayYmd } from "../format";
import { useToast } from "../components/Toast";
import { useAccount } from "../account";
import { NEED_KEY, useCanMutate } from "../auth";
import { ArrowDown, ArrowUp, Minus, Plus, Star } from "lucide-react";
import { cssVar, onThemeChange, withAlpha } from "../theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Seg } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

type RangeKey = "1y" | "3y" | "5y" | "all";
type Indicator = "none" | "macd" | "rsi";

const RANGES: { k: RangeKey; label: string; days: number | null }[] = [
  { k: "1y", label: "1年", days: 365 },
  { k: "3y", label: "3年", days: 1095 },
  { k: "5y", label: "5年", days: 1825 },
  { k: "all", label: "全部", days: null },
];

export default function Stock() {
  const { code = "" } = useParams();
  const toast = useToast();
  const [quote, setQuote] = useState<Quote | null>(null);
  const [qErr, setQErr] = useState<unknown>(null);
  const [qSrc, setQSrc] = useState("");
  const [period, setPeriod] = useState("daily");
  const [adjust, setAdjust] = useState("qfq");
  const [range, setRange] = useState<RangeKey>("3y");
  const [bars, setBars] = useState<Bar[]>([]);
  const [kErr, setKErr] = useState<unknown>(null);
  const [kLoading, setKLoading] = useState(true);
  const [ind, setInd] = useState<Indicator>("macd");
  const [showBoll, setShowBoll] = useState(false);
  const [legend, setLegend] = useState<Bar | null>(null);
  const [tab, setTab] = useState("flow");
  const { account } = useAccount();
  const [cost, setCost] = useState<number | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [ovTick, setOvTick] = useState(0);

  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const [pos, ord] = await Promise.all([
          api.paperPositions(account), api.paperOrders(account, 200)]);
        if (dead) return;
        const p = pos.data.find((x) => x.code === code);
        setCost(p && p.avg_cost > 0 ? p.avg_cost : null);
        setOrders(ord.data.filter((o) => o.symbol === code));
      } catch {
        if (!dead) { setCost(null); setOrders([]); }
      }
    })();
    return () => { dead = true; };
  }, [code, account, ovTick]);

  const loadQuote = useCallback(async () => {
    try {
      const r = await api.quote(code);
      setQuote(r.data);
      setQSrc(r.source || "");
      setQErr(null);
    } catch (e) { setQErr(e); }
  }, [code]);

  const loadKline = useCallback(async () => {
    setKLoading(true);
    try {
      const days = RANGES.find((r) => r.k === range)?.days;
      const start = days
        ? new Date(Date.now() - days * 86400_000).toISOString().slice(0, 10).replace(/-/g, "")
        : "";
      const r = await api.kline(code, period, start, "", adjust);
      setBars(r.data);
      setKErr(null);
    } catch (e) {
      setKErr(e);
      setBars([]);
    } finally { setKLoading(false); }
  }, [code, period, adjust, range]);

  useEffect(() => {
    loadQuote();
    const t = setInterval(loadQuote, 30_000);
    return () => clearInterval(t);
  }, [loadQuote]);
  useEffect(() => { loadKline(); }, [loadKline]);

  const pct = quote?.pct_chg ??
    (quote?.price != null && quote?.prev_close
      ? ((quote.price / quote.prev_close) - 1) * 100
      : null);

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2 rounded-lg border border-line bg-panel px-4 py-3">
        <div>
          <div className="text-lg font-semibold">
            {quote?.name || code}
            <span className="num ml-2 text-sm font-normal text-slate-500">{code}</span>
          </div>
          <div className="flex items-baseline gap-3">
            <span className={`num text-3xl font-semibold ${pct != null && pct > 0 ? "text-up" : pct != null && pct < 0 ? "text-down" : ""}`}>
              {fmtPrice(quote?.price)}
            </span>
            <PctText v={pct} className="text-lg" />
            <span className={`num text-sm ${pct != null && pct > 0 ? "text-up" : "text-down"}`}>
              {quote?.change != null ? fmtSigned(quote.change, 2) : ""}
            </span>
          </div>
        </div>
        <div className="grid min-w-0 basis-full grid-cols-3 gap-x-4 gap-y-1 text-xs sm:basis-0 sm:flex-1 sm:grid-cols-6 sm:text-sm">
          <Hd label="今开" v={fmtPrice(quote?.open)} />
          <Hd label="最高" v={fmtPrice(quote?.high)} cls="text-up" />
          <Hd label="最低" v={fmtPrice(quote?.low)} cls="text-down" />
          <Hd label="昨收" v={fmtPrice(quote?.prev_close)} />
          <Hd label="成交额" v={fmtAmount(quote?.amount)} />
          <Hd label="换手率" v={quote?.turnover != null ? fmtPct(quote.turnover).replace("+", "") : "—"} />
          <Hd label="PE(TTM)" v={quote?.pe_ttm != null ? fmtPrice(quote.pe_ttm, 1) : "—"} />
          <Hd label="PB" v={quote?.pb != null ? fmtPrice(quote.pb, 2) : "—"} />
        </div>
      </div>
      <div className="text-xs text-slate-500">
        数据源 {qSrc || "—"}
        {quote?.note ? ` · ${quote.note}` : ""}
        {quote?.date ? ` · ${quote.date}` : ""}
      </div>
      <ErrorBanner error={qErr} onRetry={loadQuote} />

      <div className="grid gap-4 xl:grid-cols-4">
        <div className="min-w-0 space-y-4 xl:col-span-3">
          {/* chart */}
          <Card>
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
              <Seg
                options={[["daily", "日"], ["weekly", "周"], ["monthly", "月"]]}
                value={period} onChange={setPeriod}
              />
              <Seg
                options={[["qfq", "前复权"], ["hfq", "后复权"], ["", "不复权"]]}
                value={adjust} onChange={setAdjust}
              />
              <Seg
                options={RANGES.map((r) => [r.k, r.label] as [string, string])}
                value={range} onChange={(v) => setRange(v as RangeKey)}
              />
              <span className="mx-1 h-4 w-px bg-line" />
              <Seg
                options={[["none", "无指标"], ["macd", "MACD"], ["rsi", "RSI"]]}
                value={ind} onChange={(v) => setInd(v as Indicator)}
              />
              <button
                onClick={() => setShowBoll(!showBoll)}
                className={`rounded border px-2 py-1 ${showBoll ? "border-slate-500 bg-panel2 text-slate-100" : "border-line text-slate-400"}`}
              >
                BOLL
              </button>
              {legend && (
                <span className="num ml-auto text-xs text-slate-400">
                  {legend.date} 开{fmtPrice(legend.open)} 高{fmtPrice(legend.high)}{" "}
                  低{fmtPrice(legend.low)} 收{fmtPrice(legend.close)} 量{fmtAmount(legend.volume)}手
                </span>
              )}
            </div>
            {kLoading ? <Skeleton rows={8} /> : (
              <>
                <ErrorBanner error={kErr} onRetry={loadKline} />
                {bars.length > 0 && (
                  <KChart bars={bars} ind={ind} boll={showBoll} onHover={setLegend}
                          cost={cost} orders={orders} />
                )}
              </>
            )}
          </Card>

          {/* tabs */}
          <Card>
            <div className="mb-3 overflow-x-auto">
              <Seg
                options={[["flow", "资金流向"], ["fin", "财务指标"], ["stmt", "三大报表"], ["peers", "同业对比"], ["factor", "因子快照"], ["ann", "公告"]]}
                value={tab} onChange={setTab} btnClassName="px-3 py-1.5 text-sm"
              />
            </div>
            {tab === "flow" && <FlowTab code={code} />}
            {tab === "fin" && <FinTab code={code} />}
            {tab === "stmt" && <StmtTab code={code} />}
            {tab === "peers" && <PeersTab code={code} />}
            {tab === "factor" && <FactorTab code={code} />}
            {tab === "ann" && <AnnTab code={code} />}
          </Card>
        </div>

        <QuickTrade code={code} quote={quote} toast={toast}
                    onTraded={() => setOvTick((t) => t + 1)} />
      </div>
    </div>
  );
}

function Hd({ label, v, cls = "" }: { label: string; v: string; cls?: string }) {
  return (
    <div>
      <div className="text-slate-500">{label}</div>
      <div className={`num ${cls}`}>{v}</div>
    </div>
  );
}

/* ---------- main K chart ---------- */

function KChart({ bars, ind, boll: showBoll, onHover, cost, orders }: {
  bars: Bar[]; ind: Indicator; boll: boolean;
  onHover: (b: Bar | null) => void;
  cost?: number | null; orders?: Order[];
}) {
  const paneH = ind === "none" ? 0 : 120;
  const { ref, chart } = useChart({ height: 420 + paneH });
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!chart) return;
    let offAccent: (() => void) | undefined;
    const up = UP, down = DOWN;
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: up, downColor: down, borderUpColor: up, borderDownColor: down,
      wickUpColor: up, wickDownColor: down,
    });
    seriesRef.current = candle;
    candle.setData(bars.map((b) => ({
      time: b.date, open: b.open, high: b.high, low: b.low, close: b.close,
    })));
    const vol = chart.addSeries(HistogramSeries, {
      priceScaleId: "vol", priceFormat: { type: "volume" },
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(bars.map((b) => ({
      time: b.date, value: b.volume,
      color: b.close >= b.open ? "rgba(239,83,80,0.4)" : "rgba(38,166,154,0.4)",
    })));
    // position overlay: dashed avg-cost line + buy/sell markers
    if (cost != null && cost > 0) {
      candle.createPriceLine({
        price: cost, color: "#f0b90b", lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true,
        title: `持仓成本 ${cost.toFixed(2)}`,
      });
    }
    if (orders && orders.length) {
      const barDates = [...new Set(bars.map((b) => b.date))].sort();
      const markers = orders.flatMap((o) => {
        const d = String(o.time).slice(0, 10);
        // map to the last bar on/before the order date (non-trading days roll back)
        let t = "";
        for (const bd of barDates) { if (bd <= d) t = bd; else break; }
        if (!t) return [];
        const buy = o.side === "buy";
        return [{
          time: t,
          position: buy ? "belowBar" as const : "aboveBar" as const,
          color: buy ? up : down,
          shape: buy ? "arrowUp" as const : "arrowDown" as const,
          text: `${o.shares}`,
        }];
      }).sort((a, b) => a.time.localeCompare(b.time));
      if (markers.length) createSeriesMarkers(candle, markers);
    }
    // MAs
    for (const [n, c] of [[5, "#f0b90b"], [20, "#7b7ff2"], [60, "#aab2c0"]] as const) {
      const s = chart.addSeries(LineSeries, { color: c, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      s.setData(toPts(bars, sma(bars, n)));
    }
    if (showBoll) {
      const b = boll(bars);
      for (const [vals, c] of [[b.upper, "#c084fc"], [b.mid, "#f0b90b"], [b.lower, "#c084fc"]] as const) {
        const s = chart.addSeries(LineSeries, { color: c as string, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
        s.setData(toPts(bars, vals as (number | null)[]));
      }
    }
    if (ind === "macd") {
      const m = macd(bars);
      const dif = chart.addSeries(LineSeries, { color: "#f0b90b", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, 1);
      dif.setData(toPts(bars, m.dif));
      const dea = chart.addSeries(LineSeries, { color: cssVar("--color-accent"), lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, 1);
      dea.setData(toPts(bars, m.dea));
      offAccent = onThemeChange(() =>
        dea.applyOptions({ color: cssVar("--color-accent") }));
      const hist = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, 1);
      hist.setData(bars.flatMap((b, i) =>
        m.hist[i] == null ? [] : [{
          time: b.date, value: m.hist[i]!,
          color: m.hist[i]! >= 0 ? "rgba(239,83,80,0.6)" : "rgba(38,166,154,0.6)",
        }]));
    } else if (ind === "rsi") {
      const r = chart.addSeries(LineSeries, { color: "#c084fc", lineWidth: 1, priceLineVisible: false }, 1);
      r.setData(toPts(bars, rsi(bars)));
    }
    const onMove = (p: MouseEventParams) => {
      const t = p.time as string | undefined;
      onHover(t ? bars.find((b) => b.date === t) ?? null : null);
    };
    chart.subscribeCrosshairMove(onMove);
    chart.timeScale().fitContent();
    return () => { offAccent?.(); chart.unsubscribeCrosshairMove(onMove); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chart, bars, ind, showBoll, cost, orders]);

  return <div ref={ref} className="w-full min-w-0 overflow-hidden" />;
}

/* ---------- quick trade ---------- */

function QuickTrade({ code, quote, toast, onTraded }: {
  code: string; quote: Quote | null;
  toast: (k: "ok" | "err", t: string) => void;
  onTraded?: () => void;
}) {
  const [shares, setShares] = useState(100);
  const [busy, setBusy] = useState(false);
  const [cash, setCash] = useState<number | null>(null);
  const [sellable, setSellable] = useState(0);
  const price = quote?.price ?? 0;
  const { account } = useAccount();
  const canMutate = useCanMutate();

  const refresh = useCallback(async () => {
    try {
      const [st, pos] = await Promise.all([
        api.paperStatus(account), api.paperPositions(account)]);
      setCash(st.cash);
      const p = pos.data.find((x) => x.code === code);
      setSellable(p?.available ?? 0);
    } catch { /* offline */ }
  }, [code, account]);
  useEffect(() => { refresh(); }, [refresh]);

  const amount = price * shares;
  const fee = Math.max(amount * 0.00025, 5) + amount * 0.00001;
  const maxLots = cash != null && price > 0
    ? Math.floor((cash - 5) / (price * 100 * 1.00026)) : 0;

  const trade = async (side: "buy" | "sell") => {
    setBusy(true);
    try {
      const r = side === "buy"
        ? await api.paperBuy(account, code, shares)
        : await api.paperSell(account, code, shares);
      toast("ok", `${side === "buy" ? "买入" : "卖出"}成交 ${r.code} ${r.shares}股 @ ${r.price}`);
      refresh();
      onTraded?.();
    } catch (e) {
      toast("err", `${side === "buy" ? "买入" : "卖出"}失败：${e instanceof Error ? e.message : e}`);
    } finally { setBusy(false); }
  };

  return (
    <Card title="快捷交易" className="h-fit">
      <div className="space-y-3 text-sm">
        <div className="flex justify-between">
          <span className="text-slate-400">现价</span>
          <span className="num">{fmtPrice(price)}</span>
        </div>
        <div>
          <label className="mb-1 block text-slate-400">股数（100的倍数）</label>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="icon" className="size-7 shrink-0"
              aria-label="减少100股"
              onClick={() => setShares(Math.max(100, shares - 100))}>
              <Minus className="size-3.5" />
            </Button>
            <Input
              type="number" step={100} min={100} value={shares}
              onChange={(e) => setShares(Math.max(0, Math.floor(Number(e.target.value) / 100) * 100))}
              className="num w-full text-right"
            />
            <Button variant="outline" size="icon" className="size-7 shrink-0"
              aria-label="增加100股"
              onClick={() => setShares(shares + 100)}>
              <Plus className="size-3.5" />
            </Button>
          </div>
        </div>
        <div className="space-y-1 border-t border-line pt-2 text-xs text-slate-400">
          <div className="flex justify-between"><span>预估金额</span><span className="num">{fmtAmount(amount)}</span></div>
          <div className="flex justify-between"><span>预估费用(买)</span><span className="num">{fee.toFixed(2)}</span></div>
          <div className="flex justify-between"><span>可买(约)</span><span className="num">{Math.max(0, maxLots)}手</span></div>
          <div className="flex justify-between"><span>可卖(T+1)</span><span className="num">{sellable}股</span></div>
          <div className="flex justify-between"><span>可用现金</span><span className="num">{cash != null ? fmtAmount(cash) : "—"}</span></div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Button variant="buy"
            disabled={busy || shares <= 0 || !canMutate}
            title={canMutate ? "" : NEED_KEY}
            onClick={() => trade("buy")}
            className="h-9"
          >
            买入
          </Button>
          <Button variant="sell"
            disabled={busy || shares <= 0 || !canMutate}
            title={canMutate ? "" : NEED_KEY}
            onClick={() => trade("sell")}
            className="h-9"
          >
            卖出
          </Button>
        </div>
        <p className="text-xs text-slate-500">模拟盘 · 1手=100股 · T+1 · 涨跌停校验</p>
      </div>
    </Card>
  );
}

/* ---------- tabs ---------- */

function useLoader<T>(fn: () => Promise<{ data: T; source?: string }>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [src, setSrc] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fn();
      setData(r.data);
      setSrc(r.source || "");
      setErr(null);
    } catch (e) { setErr(e); }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { load(); }, [load]);
  return { data, err, loading, src, reload: load };
}

function GenericTable({ rows }: { rows: Record<string, unknown>[] }) {
  const cols = useMemo(() => (rows.length ? Object.keys(rows[0]) : []), [rows]);
  if (!rows.length) return <EmptyState text="暂无数据" />;
  return (
    <div className="max-h-96 overflow-auto">
      <Table className="whitespace-nowrap text-xs">
        <TableHeader className="sticky top-0 bg-card">
          <TableRow className="hover:bg-transparent">
            {cols.map((c) => <TableHead key={c}>{c}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r, i) => (
            <TableRow key={i} className="hover:bg-muted/50">
              {cols.map((c) => <TableCell key={c} className="num">{cell(r[c])}</TableCell>)}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function cell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return v.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
  return String(v);
}

function SrcCap({ src }: { src: string }) {
  return src ? <p className="mt-2 text-xs text-slate-500">数据源 {src}</p> : null;
}

function FlowTab({ code }: { code: string }) {
  const { data, err, loading, src, reload } = useLoader(() => api.moneyFlow(code, 30), [code]);
  if (loading) return <Spinner />;
  const key = data?.length
    ? (Object.keys(data[0]).find((k) => k.includes("主力") && k.includes("净")) ??
       Object.keys(data[0]).find((k) => k.includes("净")))
    : undefined;
  return (
    <div>
      <ErrorBanner error={err} onRetry={reload} />
      {data && key && <FlowChart rows={data} kkey={key} />}
      {data && <GenericTable rows={data} />}
      <SrcCap src={src} />
    </div>
  );
}

function FlowChart({ rows, kkey }: { rows: Record<string, unknown>[]; kkey: string }) {
  const { ref, chart } = useChart({ height: 180 });
  useEffect(() => {
    if (!chart) return;
    const s = chart.addSeries(HistogramSeries, {});
    const dateKey = Object.keys(rows[0]).find((k) => k.includes("日期") || k === "date") ?? "date";
    s.setData(rows.flatMap((r) => {
      const v = Number(r[kkey]);
      const t = String(r[dateKey] ?? "");
      if (!t || Number.isNaN(v)) return [];
      return [{ time: t.slice(0, 10), value: v, color: v >= 0 ? "rgba(239,83,80,0.7)" : "rgba(38,166,154,0.7)" }];
    }));
    chart.timeScale().fitContent();
  }, [chart, rows, kkey]);
  return <div ref={ref} className="mb-3 w-full min-w-0 overflow-hidden" />;
}

function FinTab({ code }: { code: string }) {
  const [ind, setInd] = useState("按报告期");
  const { data, err, loading, src, reload } = useLoader(
    () => api.financial(code, ind), [code, ind]);
  return (
    <div>
      <div className="mb-2"><Seg options={[["按报告期", "按报告期"], ["按年度", "按年度"], ["按单季", "按单季"], ["累计报告期", "累计报告期"]]} value={ind} onChange={setInd} /></div>
      {loading ? <Spinner /> : (<><ErrorBanner error={err} onRetry={reload} />{data && <FinChart rows={data} />}{data && <GenericTable rows={data} />}<SrcCap src={src} /></>)}
    </div>
  );
}

/** Financial trend chart: revenue & net-profit bars + ROE/GM% lines. */
function FinChart({ rows }: { rows: Record<string, unknown>[] }) {
  const { ref, chart } = useChart({ height: 240 });
  useEffect(() => {
    if (!chart || !rows.length) return;
    const keys = Object.keys(rows[0]);
    const find = (...pats: string[]) =>
      keys.find((k) => pats.some((p) => k.includes(p)));
    // real payload: East Money field codes (TOTALOPERATEREVE=PARENTNETPROFIT
    // 等), 中文名 fallback
    const dKey = find("REPORT_DATE", "报告期", "截止日期", "日期", "date");
    const revK = find("TOTALOPERATEREVE", "营业总收入", "营业收入");
    const npK = find("PARENTNETPROFIT", "归母净利润", "净利润");
    const roeK = find("ROEJQ", "ROE", "净资产收益率");
    const gmK = find("XSMLL", "销售毛利率", "毛利率");
    if (!dKey || (!revK && !npK && !roeK && !gmK)) return;
    const num = (v: unknown) => {
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };
    const data = rows
      .map((r) => ({ r, t: String(r[dKey] ?? "").slice(0, 10) }))
      .filter((x) => x.t)
      .sort((a, b) => a.t.localeCompare(b.t))
      .slice(-12);
    // auto-scale money columns to 亿 when magnitudes look like raw CNY
    const moneyScale = ((k?: string) => {
      if (!k) return 1;
      const vals = data.map((x) => num(x.r[k])).filter((v): v is number => v != null && v > 0);
      if (!vals.length) return 1;
      const med = vals.sort((a, b) => a - b)[Math.floor(vals.length / 2)];
      return med > 1e7 ? 1e-8 : med > 1e5 ? 1e-4 : 1;   // 元→亿 | 万元→亿
    });
    const rs = moneyScale(revK || npK);
    const mk = (k: string | undefined, color: string, scale = 1) => {
      if (!k) return;
      const s = chart.addSeries(HistogramSeries, { color, priceFormat: { type: "volume" }, priceScaleId: "money" });
      chart.priceScale("money").applyOptions({ scaleMargins: { top: 0.2, bottom: 0.2 }, visible: false });
      s.setData(data.flatMap((x) => {
        const v = num(x.r[k]);
        return v == null ? [] : [{ time: x.t, value: v * scale }];
      }));
    };
    const acc = cssVar("--color-accent");
    mk(revK, withAlpha(acc, 0.75), rs);         // 营业总收入 (亿)
    mk(npK, "rgba(240,185,11,0.85)", rs);        // 归母净利润 (亿)
    chart.applyOptions({ leftPriceScale: { visible: true, borderColor: "rgba(148,163,184,0.4)" } });
    const ln = (k: string | undefined, color: string) => {
      if (!k) return;
      const s = chart.addSeries(LineSeries, { color, lineWidth: 2, priceScaleId: "left", priceLineVisible: false, lastValueVisible: false });
      s.setData(data.flatMap((x) => {
        const v = num(x.r[k]);
        return v == null ? [] : [{ time: x.t, value: v }];
      }));
    };
    ln(roeK, "#f472b6");                          // ROE %
    ln(gmK, "#06b6d4");                           // 毛利率 %
    chart.timeScale().fitContent();
  }, [chart, rows]);
  if (!rows.length) return null;
  return (
    <div className="mb-3">
      <div className="mb-1 flex flex-wrap gap-3 text-xs text-slate-500">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: "var(--color-accent)" }} />营业总收入(亿)</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: "rgba(240,185,11,0.85)" }} />归母净利润(亿)</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: "#f472b6" }} />ROE%(右轴)</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: "#06b6d4" }} />毛利率%(右轴)</span>
      </div>
      <div ref={ref} className="w-full min-w-0 overflow-hidden" />
    </div>
  );
}

function StmtTab({ code }: { code: string }) {
  const [type, setType] = useState("income");
  const { data, err, loading, src, reload } = useLoader(
    () => api.statement(code, type), [code, type]);
  return (
    <div>
      <div className="mb-2"><Seg options={[["income", "利润表"], ["balance", "资产负债表"], ["cashflow", "现金流量表"]]} value={type} onChange={setType} /></div>
      {loading ? <Spinner /> : (<><ErrorBanner error={err} onRetry={reload} />{data && <GenericTable rows={data} />}<SrcCap src={src} /></>)}
    </div>
  );
}

function FactorTab({ code }: { code: string }) {
  const { data, err, loading, src, reload } = useLoader(() => api.factor(code), [code]);
  if (loading) return <Spinner />;
  const f = data ?? {};
  const pct = (k: string) => (f[k] != null ? Number(f[k]) * 100 : null);
  const items: [string, string, number | null][] = [
    ["20日收益", "", pct("ret_20d")], ["60日收益", "", pct("ret_60d")],
    ["120日收益", "", pct("ret_120d")],
    ["年化波动(20d)", "", pct("vol_20d_ann")],
    ["Beta(120d)", "", f.beta_120d != null ? Number(f.beta_120d) : null],
    ["vs MA5", "%", f.vs_ma5_pct != null ? Number(f.vs_ma5_pct) : null],
    ["vs MA20", "%", f.vs_ma20_pct != null ? Number(f.vs_ma20_pct) : null],
    ["vs MA60", "%", f.vs_ma60_pct != null ? Number(f.vs_ma60_pct) : null],
    ["vs MA120", "%", f.vs_ma120_pct != null ? Number(f.vs_ma120_pct) : null],
    ["20日平均换手", "%", f.avg_turnover_20d != null ? Number(f.avg_turnover_20d) : null],
  ];
  return (
    <div>
      <ErrorBanner error={err} onRetry={reload} />
      {data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {items.map(([label, , v]) => (
            <div key={label} className="rounded border border-line bg-panel2 px-3 py-2">
              <div className="text-xs text-slate-500">{label}</div>
              <div className={`num text-sm ${v != null && label.startsWith("20日收益") || label.startsWith("60日") || label.startsWith("120日") || label.startsWith("vs") ? (v != null && v > 0 ? "text-up" : v != null && v < 0 ? "text-down" : "") : ""}`}>
                {v == null ? "—" : label === "Beta(120d)" ? v.toFixed(2) : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`}
              </div>
            </div>
          ))}
        </div>
      )}
      {data && <p className="mt-2 text-xs text-slate-500">{String(f.bars ?? "")} 根K线 · 数据源 {src}</p>}
    </div>
  );
}

function AnnTab({ code }: { code: string }) {
  const [day, setDay] = useState("");
  const { data, err, loading, src, reload } = useLoader(
    () => api.announcements(code, day), [code, day]);
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs text-slate-400">
        日期(YYYYMMDD，留空=今天)
        <Input
          value={day} onChange={(e) => setDay(e.target.value)} placeholder={todayYmd()}
          className="num w-32"
        />
      </div>
      {loading ? <Spinner /> : (
        <>
          <ErrorBanner error={err} onRetry={reload} />
          {data && (
            <ul className="divide-y divide-line/50 text-sm">
              {data.map((a, i) => {
                const title = String(a.title ?? a.公告标题 ?? a.name ?? "");
                const url = String(a.url ?? a.链接 ?? a.href ?? "");
                const dt = String(a.date ?? a.公告日期 ?? a.time ?? "");
                return (
                  <li key={i} className="flex items-baseline justify-between gap-3 py-2">
                    {url ? (
                      <a href={url} target="_blank" rel="noreferrer" className="text-slate-200 hover:text-up hover:underline">{title}</a>
                    ) : <span>{title}</span>}
                    <span className="num shrink-0 text-xs text-slate-500">{dt}</span>
                  </li>
                );
              })}
              {data.length === 0 && <li className="py-4 text-center text-slate-500">暂无公告</li>}
            </ul>
          )}
          <SrcCap src={src} />
        </>
      )}
    </div>
  );
}

/* ---------- industry peers tab ---------- */

type PeerMetric = "pe_ttm" | "pb" | "roe_est" | "mkt_cap";
const PEER_METRICS: [PeerMetric, string][] = [
  ["pe_ttm", "PE(TTM)"], ["pb", "PB"], ["roe_est", "ROE估算%"], ["mkt_cap", "总市值"],
];

function PeersTab({ code }: { code: string }) {
  const { data, err, loading, reload } = useLoader(
    () => api.peers(code).then((r) => ({ data: r })), [code]);
  const [sort, setSort] = useState<PeerMetric | "code">("mkt_cap");
  const [asc, setAsc] = useState(false);
  if (loading) return <Spinner />;
  if (!data) return <ErrorBanner error={err} onRetry={reload} />;
  const rows = [...data.peers].sort((a, b) => {
    if (sort === "code") return a.code.localeCompare(b.code) * (asc ? 1 : -1);
    const av = a[sort] ?? -Infinity, bv = b[sort] ?? -Infinity;
    return (av - bv) * (asc ? 1 : -1);
  });
  const click = (k: PeerMetric | "code") => {
    if (sort === k) setAsc(!asc); else { setSort(k); setAsc(k === "code"); }
  };
  const fmtM = (k: PeerMetric, v: number | null | undefined) =>
    v == null ? "—" : k === "mkt_cap" ? fmtAmount(v)
    : v.toFixed(k === "pb" ? 2 : 1);
  return (
    <div>
      <ErrorBanner error={err} onRetry={reload} />
      <div className="mb-2 text-xs text-slate-500">
        {data.industry} · 共{data.count}家 · 显示市值前{data.peers.length}家 · 行业：申万一级；ROE为PB/PE估算
      </div>
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {PEER_METRICS.map(([k, l]) => {
          const p = data.stock.percentiles?.[k];
          const med = data.medians?.[k];
          return (
            <div key={k} className="rounded-lg border border-border bg-muted/50 px-2 py-2">
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">{l}</span>
                <span className="num">{p == null ? "—" : `${p.toFixed(0)}%`}</span>
              </div>
              <div className="mt-1 h-1.5 rounded bg-border/60">
                <div className="h-1.5 rounded bg-accent" style={{ width: `${p ?? 0}%` }} />
              </div>
              <div className="mt-1 text-[10px] text-slate-500">
                行业中位 {fmtM(k, med)}
              </div>
            </div>
          );
        })}
      </div>
      <div className="max-h-96 overflow-auto">
        <Table className="whitespace-nowrap text-xs">
          <TableHeader className="sticky top-0 bg-card">
            <TableRow className="hover:bg-transparent">
              <TableHead className="cursor-pointer select-none hover:text-foreground" onClick={() => click("code")}>
                <span className="inline-flex items-center gap-0.5">代码
                  {sort === "code" && (asc
                    ? <ArrowUp className="size-3 text-accent" />
                    : <ArrowDown className="size-3 text-accent" />)}
                </span>
              </TableHead>
              <TableHead>名称</TableHead>
              <TableHead className="text-right">现价</TableHead>
              <TableHead className="text-right">涨跌%</TableHead>
              {PEER_METRICS.map(([k, l]) => (
                <TableHead key={k} onClick={() => click(k)}
                  className="cursor-pointer select-none text-right hover:text-foreground">
                  <span className="inline-flex items-center gap-0.5">
                    {l}
                    {sort === k && (asc
                      ? <ArrowUp className="size-3 text-accent" />
                      : <ArrowDown className="size-3 text-accent" />)}
                  </span>
                </TableHead>
              ))}
              <TableHead className="text-right">换手%</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.code} className={`hover:bg-muted/50 ${r.is_me ? "bg-accent/10" : ""}`}>
                <TableCell className="num">
                  <a href={`#/stock/${r.code}`} className="text-accent hover:underline">{r.code}</a>
                </TableCell>
                <TableCell>
                  {r.name}
                  {r.is_me && <Star className="ml-1 inline size-3 fill-accent text-accent" />}
                </TableCell>
                <TableCell className="num text-right">{fmtPrice(r.price)}</TableCell>
                <TableCell className={`num text-right ${(r.pct_chg ?? 0) > 0 ? "text-up" : (r.pct_chg ?? 0) < 0 ? "text-down" : ""}`}>{r.pct_chg == null ? "—" : fmtPct(r.pct_chg)}</TableCell>
                {PEER_METRICS.map(([k]) => (
                  <TableCell key={k} className="num text-right">{fmtM(k, r[k])}</TableCell>
                ))}
                <TableCell className="num text-right">{r.turnover == null ? "—" : r.turnover.toFixed(2)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
