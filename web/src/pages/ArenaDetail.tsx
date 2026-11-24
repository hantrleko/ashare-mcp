/** /arena/:id — agent detail: metrics, equity vs benchmark, positions,
 * trade timeline with reasons (newest first). */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { LineSeries } from "lightweight-charts";
import { api, type ArenaDetail, type HousePlan } from "../api";
import { HOUSE_DESC } from "./Arena";
import { Card, EmptyState, ErrorBanner, Skeleton } from "../components/ui";
import { useChart } from "../components/chart";
import { M, toDay } from "../components/bt_shared";
import { InfoTip } from "../components/InfoTip";
import { ddClass, fmtDD, fmtPct, fmtNum, fmtSigned, signedClass } from "../format";
import { ArrowLeft, ArrowRight, Check, Inbox, LineChart } from "lucide-react";
import { cssVar, onThemeChange } from "../theme";
import { BENCHMARK } from "../lib/palette";
import { fmtMetric, fmtReason } from "../lib/metrics";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

function EquityChart({ d }: { d: ArenaDetail }) {
  const { ref, chart } = useChart({ height: 240 });
  useEffect(() => {
    if (!chart || !d.series.length) return;
    const eq = chart.addSeries(LineSeries, {
      color: cssVar("--color-accent"), lineWidth: 2, priceLineVisible: false,
      title: "净值",
    });
    eq.setData(d.series.map((p) => ({ time: toDay(p.date), value: p.equity })));
    const bp = d.series.filter((p) => p.benchmark != null);
    if (bp.length) {
      const b = chart.addSeries(LineSeries, {
        color: BENCHMARK, lineWidth: 1, lineStyle: 2,
        priceLineVisible: false, title: "基准(同初始)",
      });
      b.setData(bp.map((p) => ({ time: toDay(p.date), value: p.benchmark! })));
    }
    chart.timeScale().fitContent();
    const off = onThemeChange(() =>
      eq.applyOptions({ color: cssVar("--color-accent") }));
    return () => off();
  }, [chart, d]);
  return <div ref={ref} className="w-full min-w-0 overflow-hidden" />;
}

export default function ArenaAgent() {
  const { id = "" } = useParams();
  const [d, setD] = useState<ArenaDetail | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [plan, setPlan] = useState<HousePlan | null>(null);

  const load = () => api.arenaAgent(id).then((r) => {
    setD(r);
    if (r.kind === "house") {
      api.housePlans(id).then((p) => setPlan(p.plans[0] ?? null))
        .catch(() => setPlan(null));
    }
  }).catch(setErr);
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <ErrorBanner error={err} onRetry={load} />;
  if (!d) return <Skeleton rows={8} />;

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/arena" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" /> 竞技场
        </Link>
        <h1 className="text-lg font-semibold">{d.name}</h1>
        {d.model && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            {d.model}
          </span>
        )}
        {d.kind === "house" && (
          <Badge>内置</Badge>
        )}
        <span className={`num text-sm ${signedClass(d.return)}`}>
          {fmtPct(d.return * 100)}
        </span>
      </div>
      {d.kind === "house" && HOUSE_DESC[d.id] && (
        <p className="text-xs text-slate-500">策略：{HOUSE_DESC[d.id]}</p>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <M label="净值" v={fmtNum(d.equity, 0)} />
        <M label="收益" v={fmtPct(d.return * 100)} cls={signedClass(d.return)} />
        <M label={<>超额 vs 沪深300<InfoTip term="超额收益" /></>}
           v={d.excess == null ? "—" : fmtPct(d.excess * 100)}
           cls={signedClass(d.excess)} />
        <M label={<>最大回撤<InfoTip term="最大回撤" /></>} v={fmtDD(d.max_drawdown * 100)}
           cls={ddClass(d.max_drawdown)} />
        <M label={<>夏普<InfoTip term="夏普" /></>} v={d.sharpe == null ? "—" : d.sharpe.toFixed(2)} />
        <M label={<>胜率 / 交易<InfoTip term="胜率" /></>}
           v={`${d.win_rate == null ? "—" : (d.win_rate * 100).toFixed(0) + "%"} / ${d.num_trades}`} />
      </div>

      <Card title="净值 vs 基准" className="overflow-hidden">
        <EquityChart d={d} />
      </Card>

      {plan && (
        <Card title={<span className="inline-flex items-center gap-1.5">调仓计划 {plan.plan_date} <ArrowRight className="size-3.5" /> 执行日 {plan.exec_date ?? "—"}（{plan.status === "executed" ? "已执行" : "待执行"}）</span>}>
          {plan.targets.length === 0 ? (
            <EmptyState text="本期无入选标的" className="py-3" />
          ) : (
            <div className="overflow-x-auto">
              <Table className="min-w-[480px] text-xs">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>#</TableHead>
                    <TableHead>代码</TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead>指标</TableHead>
                    <TableHead>理由</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {plan.targets.map((t) => (
                    <TableRow key={t.code} className="hover:bg-muted/50">
                      <TableCell className="num">{t.rank}</TableCell>
                      <TableCell className="num">
                        <Link to={`/stock/${t.code}`} className="text-accent hover:underline">{t.code}</Link>
                      </TableCell>
                      <TableCell>{t.name}</TableCell>
                      <TableCell className="num text-muted-foreground">
                        {Object.entries(t.metrics ?? {})
                          .map(([k, v]) => fmtMetric(k, v)).join(" ")}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{fmtReason(t.note ?? "")}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          {plan.log.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs">
              {plan.log.map((l, i) => (
                <li key={i} className={l.error ? "text-down" : "text-muted-foreground"}>
                  {l.action === "buy" ? "买入" : l.action === "sell" ? "卖出" : l.action}
                  {l.code ? ` ${l.code}` : ""}{l.shares ? ` ${l.shares}股` : ""}
                  {l.error ? ` — ${l.error}` : l.ok
                    ? <Check className="ml-1 inline size-3 text-up" />
                    : ""}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      <Card title={`持仓（${d.positions.length}）`}>
        {d.positions.length === 0 ? (
          <EmptyState icon={Inbox} text="空仓" className="py-3" />
        ) : (
          <div className="overflow-x-auto">
            <Table className="min-w-[480px]">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>代码</TableHead>
                  <TableHead>名称</TableHead>
                  <TableHead className="num">股数</TableHead>
                  <TableHead className="num">成本</TableHead>
                  <TableHead className="num">现价</TableHead>
                  <TableHead className="num">市值</TableHead>
                  <TableHead className="num">盈亏</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.positions.map((p) => (
                  <TableRow key={p.code} className="hover:bg-muted/50">
                    <TableCell className="num">
                      <Link to={`/stock/${p.code}`}
                            className="text-accent hover:underline">
                        {p.code}
                      </Link>
                    </TableCell>
                    <TableCell>{p.name}</TableCell>
                    <TableCell className="num">{fmtNum(p.shares)}</TableCell>
                    <TableCell className="num">{p.avg_cost.toFixed(2)}</TableCell>
                    <TableCell className="num">{p.last_price.toFixed(2)}</TableCell>
                    <TableCell className="num">{fmtNum(p.market_value)}</TableCell>
                    <TableCell className={`num ${signedClass(p.pnl)}`}>
                      {fmtSigned(p.pnl)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      <Card title={`交易记录（${d.trades.length}）`}>
        {d.trades.length === 0 ? (
          <EmptyState icon={LineChart} text="暂无交易" className="py-3" />
        ) : (
          <ol className="space-y-3">
            {d.trades.map((t, i) => (
              <li key={t.id ?? i} className="border-b border-line/40 pb-3 last:border-0">
                <div className="flex flex-wrap items-baseline gap-2 text-sm">
                  <span className="text-xs text-slate-500">
                    {(t.time ?? "").slice(0, 16).replace("T", " ")}
                  </span>
                  <span className={t.side === "buy" ? "text-up" : "text-down"}>
                    {t.side === "buy" ? "买入" : "卖出"}
                  </span>
                  <span className="font-medium">
                    {t.name || t.symbol}
                    <span className="num ml-1 text-xs text-slate-500">{t.symbol}</span>
                  </span>
                  <span className="num text-xs text-slate-400">
                    {fmtNum(t.shares)}股 @ {t.price?.toFixed(2)}
                    {t.realized_pnl != null && (
                      <span className={`ml-2 ${signedClass(t.realized_pnl)}`}>
                        {fmtSigned(t.realized_pnl)}
                      </span>
                    )}
                  </span>
                </div>
                <blockquote className="mt-1 border-l-2 border-line pl-3 text-xs text-slate-400">
                  {t.reason?.trim() ? fmtReason(t.reason) : "未填写理由"}
                </blockquote>
              </li>
            ))}
          </ol>
        )}
      </Card>

      <p className="text-center text-xs text-slate-600">
        模拟交易竞技场，仅供研究，不构成投资建议
      </p>
    </div>
  );
}
