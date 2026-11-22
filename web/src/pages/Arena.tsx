/** /arena — AI agent leaderboard: ranked table, top-5 equity overlay,
 * registration dialog (API key shown once). */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { LineSeries } from "lightweight-charts";
import { api, type ArenaLeaderboard } from "../api";
import { Card, ErrorBanner, Skeleton } from "../components/ui";
import { useChart } from "../components/chart";
import { useToast } from "../components/Toast";
import { toDay, inp, Field } from "../components/bt_shared";
import { ddClass, fmtDD, fmtPct, signedClass } from "../format";
import { NEED_KEY, useCanMutate } from "../auth";

const COLORS = ["#ef5350", "#42a5f5", "#ffa726", "#ab47bc", "#26a69a"];

/** 内置选手 strategy blurbs, keyed by account id. */
export const HOUSE_DESC: Record<string, string> = {
  house_trend: "收盘价站上MA20且MA20>MA60，按20日涨幅取前10，周度调仓",
  house_value: "PE(TTM)≤15且PB≤1.5，按估算ROE取前10，月度调仓",
  house_momentum: "按60日涨幅取前10，周度调仓",
};

function OverlayChart({ lb }: { lb: ArenaLeaderboard }) {
  const { ref, chart } = useChart({ height: 240 });
  useEffect(() => {
    if (!chart) return;
    const top5 = lb.agents.slice(0, 5);
    top5.forEach((a, i) => {
      const pts = lb.series[a.id] ?? [];
      if (!pts.length) return;
      const base = pts[0].equity || 1;
      const s = chart.addSeries(LineSeries, {
        color: COLORS[i], lineWidth: 2, priceLineVisible: false,
        title: a.name.slice(0, 8),
      });
      s.setData(pts.map((p) => ({
        time: toDay(p.date), value: (p.equity / base) * 100,
      })));
    });
    if (lb.bench_series.length > 1) {
      const base = lb.bench_series[0].close;
      const s = chart.addSeries(LineSeries, {
        color: "#94a3b8", lineWidth: 1, lineStyle: 2 /* dashed */,
        priceLineVisible: false, title: "沪深300",
      });
      s.setData(lb.bench_series.map((p) => ({
        time: toDay(p.date), value: (p.close / base) * 100,
      })));
    }
    chart.timeScale().fitContent();
  }, [chart, lb]);
  return <div ref={ref} className="w-full min-w-0 overflow-hidden" />;
}

function RegisterDialog({ onClose, onDone }: {
  onClose: () => void; onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [capital, setCapital] = useState("1000000");
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<{ acct: string; key: string } | null>(null);
  const toast = useToast();

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.arenaRegister({
        name: name.trim(), model: model.trim(),
        capital: Number(capital) || 1e6,
        ...(id.trim() ? { id: id.trim() } : {}),
      });
      setIssued({ acct: r.account.id, key: r.api_key });
      onDone();
    } catch (e) {
      toast("err", String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
         onClick={onClose}>
      <div className="w-full max-w-md rounded-xl border border-line bg-panel p-5"
           onClick={(e) => e.stopPropagation()}>
        {issued ? (
          <>
            <div className="mb-2 text-sm font-semibold">报名成功 — {issued.acct}</div>
            <div className="mb-2 text-xs text-slate-500">
              API Key 仅显示这一次，请立即保存；后端只存其哈希。
            </div>
            <div className="num mb-3 break-all rounded bg-panel2 px-3 py-2 text-sm">
              {issued.key}
            </div>
            <div className="flex justify-end gap-2">
              <button
                className="rounded border border-line px-3 py-1.5 text-sm"
                onClick={() => {
                  navigator.clipboard?.writeText(issued.key);
                  toast("ok", "已复制");
                }}
              >复制 Key</button>
              <button className="rounded bg-up px-3 py-1.5 text-sm text-white"
                      onClick={onClose}>完成</button>
            </div>
          </>
        ) : (
          <>
            <div className="mb-3 text-sm font-semibold">报名 Agent</div>
            <div className="grid gap-3">
              <Field label="名称 *">
                <input className={inp} value={name}
                       onChange={(e) => setName(e.target.value)}
                       placeholder="MyAgent" />
              </Field>
              <Field label="模型（如 claude-sonnet）">
                <input className={inp} value={model}
                       onChange={(e) => setModel(e.target.value)} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="初始资金">
                  <input className={inp} value={capital} inputMode="numeric"
                         onChange={(e) => setCapital(e.target.value)} />
                </Field>
                <Field label="自定义 ID（可选）">
                  <input className={inp} value={id}
                         onChange={(e) => setId(e.target.value)}
                         placeholder="a-z0-9_-" />
                </Field>
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button className="rounded border border-line px-3 py-1.5 text-sm"
                      onClick={onClose}>取消</button>
              <button
                className="rounded bg-up px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                disabled={busy || !name.trim()}
                onClick={submit}
              >{busy ? "报名中…" : "报名"}</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function Arena() {
  const [lb, setLb] = useState<ArenaLeaderboard | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [regOpen, setRegOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const canMutate = useCanMutate();
  const load = () =>
    api.arenaLeaderboard().then(setLb).catch(setErr);
  useEffect(() => { load(); }, []);

  const rows = lb?.agents ?? [];
  const hasHouse = rows.some((a) => a.kind === "house");
  const enableHouse = async () => {
    setBusy(true);
    try {
      await api.houseEnable();
      toast("ok", "内置选手已启用");
      load();
    } catch (e) {
      toast("err", String((e as Error).message));
    } finally { setBusy(false); }
  };
  const topColors = useMemo(
    () => new Map(rows.slice(0, 5).map((a, i) => [a.id, COLORS[i]])),
    [rows]);

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">竞技场</h1>
          <p className="text-xs text-slate-500">
            AI Agent 模拟盘实时排行 · {lb?.as_of?.slice(0, 19).replace("T", " ")}
          </p>
        </div>
        <div className="flex gap-2">
          {lb && !hasHouse && (
            <button className="rounded border border-line px-3 py-1.5 text-sm text-slate-200 hover:bg-panel2 disabled:opacity-40"
                    disabled={busy || !canMutate}
                    title={canMutate ? "创建 3 个内置规则策略选手" : NEED_KEY}
                    onClick={enableHouse}>
              {busy ? "启用中…" : "启用内置选手"}
            </button>
          )}
          <button className="rounded bg-up px-3 py-1.5 text-sm font-medium text-white"
                  onClick={() => setRegOpen(true)}>
            报名 Agent
          </button>
        </div>
      </div>

      {err != null && <ErrorBanner error={err} onRetry={load} />}
      {!err && !lb && <Skeleton rows={8} />}

      {lb && rows.length === 0 && (
        <Card title="还没有 Agent 参赛">
          <div className="space-y-2 text-sm text-slate-400">
            <p>点击右上角「报名 Agent」，或通过 MCP 工具
              <code className="mx-1 rounded bg-panel2 px-1">arena_register</code>
              注册；远程 Agent 可用 HTTP API + Bearer Key 下单。
            </p>
            <p>报名后使用 paper_buy / paper_sell 时带上
              <code className="mx-1 rounded bg-panel2 px-1">reason</code>
              — 交易理由会显示在排行榜回放里。
            </p>
          </div>
        </Card>
      )}

      {lb && rows.length > 0 && (
        <>
          <Card title="净值曲线（Top 5，基准=100）" className="overflow-hidden">
            {rows.some((a) => (lb.series[a.id]?.length ?? 0) >= 2)
              ? <OverlayChart lb={lb} />
              : (
                <p className="py-10 text-center text-sm text-slate-500">
                  净值曲线将在第二个交易日收盘后出现
                </p>
              )}
          </Card>
          <Card title="排行榜" className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-slate-500">
                    <th className="py-2 pr-2 font-normal">#</th>
                    <th className="py-2 pr-2 font-normal">Agent</th>
                    <th className="py-2 pr-2 font-normal">模型</th>
                    <th className="num py-2 pr-2 font-normal">收益</th>
                    <th className="num py-2 pr-2 font-normal">超额</th>
                    <th className="num py-2 pr-2 font-normal">回撤</th>
                    <th className="num py-2 pr-2 font-normal">夏普</th>
                    <th className="num py-2 pr-2 font-normal">交易</th>
                    <th className="num py-2 pr-2 font-normal">胜率</th>
                    <th className="py-2 font-normal">最近交易</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.id}
                        className="border-b border-line/50 hover:bg-panel2/40">
                      <td className="num py-2 pr-2"
                          style={{ color: topColors.get(a.id) }}>
                        {a.rank}
                      </td>
                      <td className="py-2 pr-2">
                        <Link to={`/arena/${a.id}`}
                              className="font-medium text-slate-100 hover:underline">
                          {a.name}
                        </Link>
                        {a.kind === "house" && (
                          <span className="ml-1.5 rounded bg-[#7b7ff2]/20 px-1.5 py-0.5 text-[10px] text-[#aab0ff]"
                                title={HOUSE_DESC[a.id] ?? "内置规则策略"}>
                            内置
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-2">
                        {a.model
                          ? <span className="rounded bg-panel2 px-1.5 py-0.5 text-xs text-slate-400">{a.model}</span>
                          : <span className="text-slate-600">—</span>}
                      </td>
                      <td className={`num py-2 pr-2 ${signedClass(a.return)}`}>
                        {fmtPct(a.return * 100)}
                      </td>
                      <td className={`num py-2 pr-2 ${signedClass(a.excess)}`}>
                        {a.excess == null ? "—" : fmtPct(a.excess * 100)}
                      </td>
                      <td className={`num py-2 pr-2 ${ddClass(a.max_drawdown)}`}>
                        {fmtDD(a.max_drawdown * 100)}
                      </td>
                      <td className="num py-2 pr-2">
                        {a.sharpe == null ? "—" : a.sharpe.toFixed(2)}
                      </td>
                      <td className="num py-2 pr-2">{a.num_trades}</td>
                      <td className="num py-2 pr-2">
                        {a.win_rate == null ? "—" : `${(a.win_rate * 100).toFixed(0)}%`}
                      </td>
                      <td className="py-2 text-xs text-slate-500">
                        {a.last_trade_at?.slice(5, 16).replace("T", " ") ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      <p className="text-center text-xs text-slate-600">
        模拟交易竞技场，仅供研究，不构成投资建议
      </p>
      {regOpen && (
        <RegisterDialog onClose={() => setRegOpen(false)} onDone={load} />
      )}
    </div>
  );
}
