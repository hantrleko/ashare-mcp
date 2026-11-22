/** /arena/:id — agent detail: metrics, equity vs benchmark, positions,
 * trade timeline with reasons (newest first). */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { LineSeries } from "lightweight-charts";
import { api, type ArenaDetail } from "../api";
import { Card, ErrorBanner, Skeleton } from "../components/ui";
import { useChart } from "../components/chart";
import { M, toDay } from "../components/bt_shared";
import { ddClass, fmtDD, fmtPct, fmtNum, fmtSigned, signedClass } from "../format";

function EquityChart({ d }: { d: ArenaDetail }) {
  const { ref, chart } = useChart({ height: 240 });
  useEffect(() => {
    if (!chart || !d.series.length) return;
    const eq = chart.addSeries(LineSeries, {
      color: "#ef5350", lineWidth: 2, priceLineVisible: false,
      title: "净值",
    });
    eq.setData(d.series.map((p) => ({ time: toDay(p.date), value: p.equity })));
    const bp = d.series.filter((p) => p.benchmark != null);
    if (bp.length) {
      const b = chart.addSeries(LineSeries, {
        color: "#94a3b8", lineWidth: 1, lineStyle: 2,
        priceLineVisible: false, title: "基准(同初始)",
      });
      b.setData(bp.map((p) => ({ time: toDay(p.date), value: p.benchmark! })));
    }
    chart.timeScale().fitContent();
  }, [chart, d]);
  return <div ref={ref} className="w-full min-w-0 overflow-hidden" />;
}

export default function ArenaAgent() {
  const { id = "" } = useParams();
  const [d, setD] = useState<ArenaDetail | null>(null);
  const [err, setErr] = useState<unknown>(null);

  const load = () => api.arenaAgent(id).then(setD).catch(setErr);
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <ErrorBanner error={err} onRetry={load} />;
  if (!d) return <Skeleton rows={8} />;

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/arena" className="text-sm text-slate-500 hover:text-slate-300">
          ← 竞技场
        </Link>
        <h1 className="text-lg font-semibold">{d.name}</h1>
        {d.model && (
          <span className="rounded bg-panel2 px-1.5 py-0.5 text-xs text-slate-400">
            {d.model}
          </span>
        )}
        <span className={`num text-sm ${signedClass(d.return)}`}>
          {fmtPct(d.return * 100)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <M label="净值" v={fmtNum(d.equity, 0)} />
        <M label="收益" v={fmtPct(d.return * 100)} cls={signedClass(d.return)} />
        <M label="超额 vs 沪深300"
           v={d.excess == null ? "—" : fmtPct(d.excess * 100)}
           cls={signedClass(d.excess)} />
        <M label="最大回撤" v={fmtDD(d.max_drawdown * 100)}
           cls={ddClass(d.max_drawdown)} />
        <M label="夏普" v={d.sharpe == null ? "—" : d.sharpe.toFixed(2)} />
        <M label="胜率 / 交易"
           v={`${d.win_rate == null ? "—" : (d.win_rate * 100).toFixed(0) + "%"} / ${d.num_trades}`} />
      </div>

      <Card title="净值 vs 基准" className="overflow-hidden">
        <EquityChart d={d} />
      </Card>

      <Card title={`持仓（${d.positions.length}）`}>
        {d.positions.length === 0 ? (
          <div className="text-sm text-slate-500">空仓</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-slate-500">
                  <th className="py-2 pr-2 font-normal">代码</th>
                  <th className="py-2 pr-2 font-normal">名称</th>
                  <th className="num py-2 pr-2 font-normal">股数</th>
                  <th className="num py-2 pr-2 font-normal">成本</th>
                  <th className="num py-2 pr-2 font-normal">现价</th>
                  <th className="num py-2 pr-2 font-normal">市值</th>
                  <th className="num py-2 font-normal">盈亏</th>
                </tr>
              </thead>
              <tbody>
                {d.positions.map((p) => (
                  <tr key={p.code} className="border-b border-line/50">
                    <td className="num py-2 pr-2">
                      <Link to={`/stock/${p.code}`}
                            className="text-slate-200 hover:underline">
                        {p.code}
                      </Link>
                    </td>
                    <td className="py-2 pr-2">{p.name}</td>
                    <td className="num py-2 pr-2">{fmtNum(p.shares)}</td>
                    <td className="num py-2 pr-2">{p.avg_cost.toFixed(2)}</td>
                    <td className="num py-2 pr-2">{p.last_price.toFixed(2)}</td>
                    <td className="num py-2 pr-2">{fmtNum(p.market_value)}</td>
                    <td className={`num py-2 ${signedClass(p.pnl)}`}>
                      {fmtSigned(p.pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={`交易记录（${d.trades.length}）`}>
        {d.trades.length === 0 ? (
          <div className="text-sm text-slate-500">暂无交易</div>
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
                  {t.reason?.trim() ? t.reason : "未填写理由"}
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
