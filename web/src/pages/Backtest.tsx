import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CandlestickSeries, LineSeries, createSeriesMarkers } from "lightweight-charts";
import { api, type BacktestResult, type Bar } from "../api";
import { Card, EmptyState, ErrorBanner } from "../components/ui";
import { useChart } from "../components/chart";
import { SearchBox } from "../components/SearchBox";
import { Field, M, inp, toDay, DrawdownChart, MonthlyHeatmap } from "../components/bt_shared";
import BtPortfolio from "./BtPortfolio";
import BtScan from "./BtScan";
import { DOWN, UP, ddClass, fmtDD, fmtNum, fmtPct, fmtPrice, fmtSigned, signedClass, todayYmd } from "../format";
import { cssVar, onThemeChange } from "../theme";
import { BENCHMARK } from "../lib/palette";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { Seg } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const STRAT: Record<string, { label: string; desc: string; params: [string, string, number][] }> = {
  ma_cross: { label: "均线交叉", desc: "快线上穿慢线持有", params: [["fast", "快线周期", 5], ["slow", "慢线周期", 20]] },
  momentum: { label: "动量", desc: "N日涨幅超过阈值持有", params: [["lookback", "回望天数", 20], ["threshold", "动量阈值", 0.03]] },
  grid: { label: "网格", desc: "价格区间分档，低位满仓高位空仓", params: [["grids", "网格数", 10], ["lower", "下沿(0=自动)", 0], ["upper", "上沿(0=自动)", 0]] },
  buy_hold: { label: "买入持有", desc: "基准：全程持有", params: [] },
};

const TABS: [string, string][] = [
  ["single", "单股"], ["portfolio", "组合"], ["scan", "参数扫描"],
];

export default function Backtest() {
  const [sp, setSp] = useSearchParams();
  const mode = TABS.some(([k]) => k === sp.get("mode")) ? sp.get("mode")! : "single";

  if (mode === "portfolio") {
    return (
      <div className="space-y-4">
        <TabBar mode={mode} setSp={setSp} />
        <BtPortfolio
          initial={{ codes: (sp.get("codes") || "").split(",").filter(Boolean) }}
          autoRun={sp.get("run") === "1"} />
      </div>
    );
  }
  if (mode === "scan") {
    return (
      <div className="space-y-4">
        <TabBar mode={mode} setSp={setSp} />
        <BtScan />
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <TabBar mode={mode} setSp={setSp} />
      <SingleBacktest sp={sp} />
    </div>
  );
}

function TabBar({ mode, setSp }: { mode: string; setSp: ReturnType<typeof useSearchParams>[1] }) {
  return (
    <Seg
      options={TABS}
      value={mode}
      onChange={(k) => setSp(k === "single" ? {} : { mode: k })}
      className="flex w-full p-1"
      btnClassName="flex-1 px-3 py-1.5 text-sm"
    />
  );
}

function SingleBacktest({ sp }: { sp: URLSearchParams }) {
  const [symbol, setSymbol] = useState(sp.get("code") || "000001");
  const [strategy, setStrategy] = useState(
    sp.get("strategy") && STRAT[sp.get("strategy")!] ? sp.get("strategy")! : "ma_cross");
  const [params, setParams] = useState<Record<string, string>>({ fast: "5", slow: "20" });
  const [start, setStart] = useState(sp.get("start") || "20240101");
  const [end, setEnd] = useState(sp.get("end") || todayYmd());
  const [capital, setCapital] = useState(
    Number(sp.get("capital")) > 0 ? Number(sp.get("capital")) : 1_000_000);
  const [slip, setSlip] = useState(Number(sp.get("slippage_bps")) || 0);
  const [mtv, setMtv] = useState(Number(sp.get("min_trade_value")) || 5000);
  const didAutoRun = useRef(false);
  const [res, setRes] = useState<BacktestResult | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      const p: Record<string, number | null> = {};
      for (const [k] of STRAT[strategy].params) {
        const v = Number(params[k]);
        p[k] = Number.isFinite(v) && v !== 0 ? v : null;
      }
      const [bt, kl] = await Promise.all([
        api.backtest({
          symbol, strategy, params: p, start, end,
          capital, slippage_bps: slip, min_trade_value: mtv,
        }),
        api.kline(symbol, "daily", start, end, "qfq").catch(() => ({ data: [] as Bar[] })),
      ]);
      setRes(bt);
      setBars(kl.data);
    } catch (e) { setErr(e); }
    finally { setBusy(false); }
  };

  // deep link: #/backtest?code=…&strategy=…&run=1 auto-runs once
  useEffect(() => {
    if (sp.get("run") === "1" && !didAutoRun.current) {
      didAutoRun.current = true;
      run();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        信号在收盘产生、次日开盘成交（无未来函数）· 做多 · 含真实费用 · 低于最小交易额的交易跳过（清仓除外）
      </p>
      <Card title="回测参数">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <div>
            <Label>代码</Label>
            <div className="flex gap-1">
              <Input value={symbol} onChange={(e) => setSymbol(e.target.value)}
                className="num w-full" />
            </div>
            <SearchBox className="mt-1" onPick={(h) => setSymbol(h.code)} />
          </div>
          <div>
            <Label>策略</Label>
            <Select value={strategy} onChange={(e) => {
              const s = e.target.value;
              setStrategy(s);
              const p: Record<string, string> = {};
              for (const [k, , d] of STRAT[s].params) p[k] = String(d);
              setParams(p);
            }} className="w-full">
              {Object.entries(STRAT).map(([k, v]) => (
                <option key={k} value={k}>{v.label} — {v.desc}</option>
              ))}
            </Select>
          </div>
          {STRAT[strategy].params.map(([k, label]) => (
            <div key={k}>
              <Label>{label}</Label>
              <Input value={params[k] ?? ""} onChange={(e) => setParams({ ...params, [k]: e.target.value })}
                className="num w-full" />
            </div>
          ))}
          <Field label="开始日期"><input value={start} onChange={(e) => setStart(e.target.value)} className={inp} /></Field>
          <Field label="结束日期"><input value={end} onChange={(e) => setEnd(e.target.value)} className={inp} /></Field>
          <Field label="初始资金"><input type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} className={inp} /></Field>
          <Field label="滑点(bps)"><input type="number" value={slip} onChange={(e) => setSlip(Number(e.target.value))} className={inp} /></Field>
          <Field label="最小交易额"><input type="number" value={mtv} onChange={(e) => setMtv(Number(e.target.value))} className={inp} /></Field>
          <div className="flex items-end">
            <Button onClick={run} disabled={busy} className="w-full">
              {busy ? "回测中…" : "运行回测"}
            </Button>
          </div>
        </div>
      </Card>
      <ErrorBanner error={err} />

      {res && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-6">
            <M label="期末资产" v={fmtNum(res.final_equity)} />
            <M label="总收益" v={fmtPct(res.total_return * 100)} cls={signedClass(res.total_return)} />
            <M label="年化" v={fmtPct(res.annual_return * 100)} cls={signedClass(res.annual_return)} />
            <M label="最大回撤" v={fmtDD(res.max_drawdown * 100)} cls={ddClass(res.max_drawdown)} />
            <M label="Sharpe" v={res.sharpe.toFixed(2)} />
            <M label="交易/胜率" v={`${res.num_trades}笔 / ${res.win_rate != null ? (res.win_rate * 100).toFixed(0) + "%" : "—"}`} />
          </div>
          <p className="text-xs text-slate-500">
            {res.symbol} · {res.start}–{res.end} · {res.bars}根K线 · 数据源 {res.source ?? "—"}
          </p>

          <Card title="净值 vs 买入持有">
            <EquityVsBench res={res} />
          </Card>

          <Card title="回撤">
            <DrawdownChart curve={res.equity_curve} />
          </Card>

          {res.monthly_returns?.length > 0 && (
            <Card title="月度收益">
              <MonthlyHeatmap data={res.monthly_returns} />
            </Card>
          )}

          <Card title="价格与交易点">
            <PriceWithTrades bars={bars} res={res} />
          </Card>

          {res.trades.length > 0 && (
            <Card title={`交易明细（最近${res.trades.length}笔）`}>
              <div className="max-h-80 overflow-x-auto">
                <Table className="whitespace-nowrap text-xs">
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      {["日期", "方向", "价格", "股数", "金额", "费用", "盈亏"].map((h) => (
                        <TableHead key={h}>{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {[...res.trades].reverse().map((t, i) => (
                      <TableRow key={i} className="hover:bg-muted/50">
                        <TableCell className="num text-muted-foreground">{t.date}</TableCell>
                        <TableCell className={t.side === "buy" ? "text-up" : "text-down"}>
                          {t.side === "buy" ? "买入" : "卖出"}
                        </TableCell>
                        <TableCell className="num">{fmtPrice(t.price)}</TableCell>
                        <TableCell className="num">{t.shares}</TableCell>
                        <TableCell className="num">{fmtNum(t.amount)}</TableCell>
                        <TableCell className="num">{t.fee.toFixed(2)}</TableCell>
                        <TableCell className={`num ${signedClass(t.pnl)}`}>
                          {t.pnl != null ? fmtSigned(t.pnl) : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function EquityVsBench({ res }: { res: BacktestResult }) {
  const { ref, chart } = useChart({ height: 320 });
  useEffect(() => {
    if (!chart) return;
    const s1 = chart.addSeries(LineSeries, {
      color: cssVar("--color-accent"), lineWidth: 2, title: "策略",
    });
    s1.setData(res.equity_curve.map((p) => ({ time: toDay(p.date), value: p.equity })));
    const s2 = chart.addSeries(LineSeries, { color: BENCHMARK, lineWidth: 1, lineStyle: 2, title: "买入持有" });
    s2.setData(res.benchmark.map((p) => ({ time: toDay(p.date), value: p.equity })));
    chart.timeScale().fitContent();
    const off = onThemeChange(() =>
      s1.applyOptions({ color: cssVar("--color-accent") }));
    return () => off();
  }, [chart, res]);
  return (
    <div>
      <div className="mb-1 flex gap-4 text-xs text-slate-400">
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-accent align-middle" />策略</span>
        <span><span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: BENCHMARK }} />买入持有</span>
      </div>
      <div ref={ref} className="w-full min-w-0 overflow-hidden" />
    </div>
  );
}

function PriceWithTrades({ bars, res }: { bars: Bar[]; res: BacktestResult }) {
  const { ref, chart } = useChart({ height: 320 });
  useEffect(() => {
    if (!chart || !bars.length) return;
    const s = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN,
      wickUpColor: UP, wickDownColor: DOWN,
    });
    s.setData(bars.map((b) => ({ time: toDay(b.date), open: b.open, high: b.high, low: b.low, close: b.close })));
    const markers = res.trades.map((t) => ({
      time: toDay(t.date),
      position: t.side === "buy" ? "belowBar" as const : "aboveBar" as const,
      color: t.side === "buy" ? UP : DOWN,
      shape: t.side === "buy" ? "arrowUp" as const : "arrowDown" as const,
      text: t.side === "buy" ? "B" : "S",
    })).sort((a, b) => a.time.localeCompare(b.time));
    createSeriesMarkers(s, markers);
    chart.timeScale().fitContent();
  }, [chart, bars, res]);
  if (!bars.length) return <EmptyState text="K线数据不可用，无法绘制交易点" />;
  return <div ref={ref} className="w-full min-w-0 overflow-hidden" />;
}
