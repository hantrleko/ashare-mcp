import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  CandlestickSeries, HistogramSeries, LineSeries,
  type ISeriesApi, type MouseEventParams,
} from "lightweight-charts";
import { api, type Bar, type Quote } from "../api";
import { boll, macd, rsi, sma, toPts } from "../indicators";
import { Card, ErrorBanner, PctText, Skeleton, Spinner, useChart } from "../components/ui";
import { DOWN, UP, fmtAmount, fmtPct, fmtPrice, fmtSigned, todayYmd } from "../format";
import { useToast } from "../components/Toast";
import { useAccount } from "../account";

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
        <div className="grid flex-1 grid-cols-3 gap-x-4 gap-y-1 text-xs sm:grid-cols-6 sm:text-sm">
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
        <div className="space-y-4 xl:col-span-3">
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
                  低{fmtPrice(legend.low)} 收{fmtPrice(legend.close)} 量{fmtAmount(legend.volume)}
                </span>
              )}
            </div>
            {kLoading ? <Skeleton rows={8} /> : (
              <>
                <ErrorBanner error={kErr} onRetry={loadKline} />
                {bars.length > 0 && (
                  <KChart bars={bars} ind={ind} boll={showBoll} onHover={setLegend} />
                )}
              </>
            )}
          </Card>

          {/* tabs */}
          <Card>
            <div className="mb-3 flex gap-1 border-b border-line text-sm">
              {[["flow", "资金流向"], ["fin", "财务指标"], ["stmt", "三大报表"], ["factor", "因子快照"], ["ann", "公告"]].map(([k, l]) => (
                <button
                  key={k}
                  onClick={() => setTab(k)}
                  className={`px-3 py-2 ${tab === k ? "border-b-2 border-up text-slate-100" : "text-slate-400 hover:text-slate-200"}`}
                >
                  {l}
                </button>
              ))}
            </div>
            {tab === "flow" && <FlowTab code={code} />}
            {tab === "fin" && <FinTab code={code} />}
            {tab === "stmt" && <StmtTab code={code} />}
            {tab === "factor" && <FactorTab code={code} />}
            {tab === "ann" && <AnnTab code={code} />}
          </Card>
        </div>

        <QuickTrade code={code} quote={quote} toast={toast} />
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

function Seg({ options, value, onChange }: {
  options: [string, string][]; value: string; onChange: (v: string) => void;
}) {
  return (
    <div className="flex overflow-hidden rounded border border-line">
      {options.map(([v, l]) => (
        <button
          key={v}
          onClick={() => onChange(v)}
          className={`px-2 py-1 ${v === value ? "bg-panel2 text-slate-100" : "text-slate-400 hover:text-slate-200"}`}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

/* ---------- main K chart ---------- */

function KChart({ bars, ind, boll: showBoll, onHover }: {
  bars: Bar[]; ind: Indicator; boll: boolean; onHover: (b: Bar | null) => void;
}) {
  const paneH = ind === "none" ? 0 : 120;
  const { ref, chart } = useChart({ height: 420 + paneH });
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!chart) return;
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
      const dea = chart.addSeries(LineSeries, { color: "#7b7ff2", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, 1);
      dea.setData(toPts(bars, m.dea));
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
    return () => chart.unsubscribeCrosshairMove(onMove);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chart, bars, ind, showBoll]);

  return <div ref={ref} className="w-full" />;
}

/* ---------- quick trade ---------- */

function QuickTrade({ code, quote, toast }: {
  code: string; quote: Quote | null;
  toast: (k: "ok" | "err", t: string) => void;
}) {
  const [shares, setShares] = useState(100);
  const [busy, setBusy] = useState(false);
  const [cash, setCash] = useState<number | null>(null);
  const [sellable, setSellable] = useState(0);
  const price = quote?.price ?? 0;
  const { account } = useAccount();

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
            <button onClick={() => setShares(Math.max(100, shares - 100))} className="rounded border border-line px-2 py-1">−</button>
            <input
              type="number" step={100} min={100} value={shares}
              onChange={(e) => setShares(Math.max(0, Math.floor(Number(e.target.value) / 100) * 100))}
              className="num w-full rounded border border-line bg-panel2 px-2 py-1 text-right outline-none"
            />
            <button onClick={() => setShares(shares + 100)} className="rounded border border-line px-2 py-1">＋</button>
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
          <button
            disabled={busy || shares <= 0}
            onClick={() => trade("buy")}
            className="rounded bg-up/90 py-2 font-medium text-white hover:bg-up disabled:opacity-40"
          >
            买入
          </button>
          <button
            disabled={busy || shares <= 0}
            onClick={() => trade("sell")}
            className="rounded bg-down/90 py-2 font-medium text-white hover:bg-down disabled:opacity-40"
          >
            卖出
          </button>
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
  if (!rows.length) return <p className="py-4 text-center text-sm text-slate-500">暂无数据</p>;
  return (
    <div className="max-h-96 overflow-auto">
      <table className="w-full whitespace-nowrap text-xs">
        <thead className="sticky top-0 bg-panel">
          <tr className="border-b border-line text-left text-slate-500">
            {cols.map((c) => <th key={c} className="px-2 py-1.5 font-normal">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line/40 hover:bg-panel2">
              {cols.map((c) => <td key={c} className="num px-2 py-1.5">{cell(r[c])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
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
  return <div ref={ref} className="mb-3 w-full" />;
}

function FinTab({ code }: { code: string }) {
  const [ind, setInd] = useState("按报告期");
  const { data, err, loading, src, reload } = useLoader(
    () => api.financial(code, ind), [code, ind]);
  return (
    <div>
      <div className="mb-2"><Seg options={[["按报告期", "按报告期"], ["按年度", "按年度"], ["按单季", "按单季"], ["累计报告期", "累计报告期"]]} value={ind} onChange={setInd} /></div>
      {loading ? <Spinner /> : (<><ErrorBanner error={err} onRetry={reload} />{data && <GenericTable rows={data} />}<SrcCap src={src} /></>)}
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
        <input
          value={day} onChange={(e) => setDay(e.target.value)} placeholder={todayYmd()}
          className="num w-32 rounded border border-line bg-panel2 px-2 py-1 outline-none"
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
