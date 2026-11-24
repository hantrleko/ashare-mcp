/** /arena — AI agent leaderboard: ranked table, top-5 equity overlay,
 * registration dialog (API key shown once). */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { LineSeries } from "lightweight-charts";
import { api, type ArenaLeaderboard, type ArenaPreview } from "../api";
import { Card, EmptyState, ErrorBanner, Skeleton } from "../components/ui";
import { useChart } from "../components/chart";
import { useToast } from "../components/Toast";
import { toDay, inp, Field } from "../components/bt_shared";
import { ddClass, fmtDD, fmtPct, signedClass } from "../format";
import { NEED_KEY, useCanMutate } from "../auth";
import { Trophy } from "lucide-react";
import { SERIES, BENCHMARK } from "../lib/palette";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { PageIntro } from "../components/Intro";
import { InfoTip } from "../components/InfoTip";
import { cssVar, onThemeChange } from "../theme";

const COLORS = SERIES;

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
        color: BENCHMARK, lineWidth: 1, lineStyle: 2 /* dashed */,
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
              <Button variant="outline"
                onClick={() => {
                  navigator.clipboard?.writeText(issued.key);
                  toast("ok", "已复制");
                }}
              >复制 Key</Button>
              <Button onClick={onClose}>完成</Button>
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
              <Button variant="outline" onClick={onClose}>取消</Button>
              <Button
                disabled={busy || !name.trim()}
                onClick={submit}
              >{busy ? "报名中…" : "报名"}</Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function PreviewChart({ pv }: { pv: ArenaPreview }) {
  const { ref, chart } = useChart({ height: 260 });
  useEffect(() => {
    if (!chart || !pv.dates || !pv.series) return;
    const defs: [keyof typeof pv.series, string, string][] = [
      ["trend", "趋势跟踪", cssVar("--color-accent")],
      ["momentum", "动量", SERIES[3]],
      ["bench", "沪深300", BENCHMARK],
    ];
    const added = defs.map(([k, title, color]) => {
      const s = chart.addSeries(LineSeries, { color, lineWidth: 2, title });
      s.setData(pv.dates!.map((d, i) => ({
        time: toDay(d), value: pv.series![k][i] * 100,
      })));
      return s;
    });
    chart.timeScale().fitContent();
    const off = onThemeChange(() =>
      added[0].applyOptions({ color: cssVar("--color-accent") }));
    return () => off();
  }, [chart, pv]);
  return <div ref={ref} className="w-full min-w-0 overflow-hidden" />;
}

function PreviewCard({ busy, onEnable }: { busy: boolean; onEnable: () => void }) {
  const [pv, setPv] = useState<ArenaPreview | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.arenaPreview().then(setPv).catch(setErr); }, []);
  if (err) return null;
  if (!pv) return <Skeleton rows={4} />;
  if (pv.state === "running")
    return <Card><EmptyState text="规则回测预览计算中（后台预热任务）…" /></Card>;
  if (pv.state !== "ready" || !pv.series) return null;
  const st = pv.stats ?? {};
  const latest = pv.latest ?? { trend: [], momentum: [] };
  return (
    <Card title={<>内置规则近半年回测预览（非实盘记录）<InfoTip term="幸存者偏差" /></>}
          className="overflow-hidden">
      <PreviewChart pv={pv} />
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <span>趋势跟踪 {st.trend ? fmtPct(st.trend.total * 100) : "—"} · 回撤 {st.trend ? fmtDD(st.trend.max_dd * 100) : "—"}</span>
        <span>动量 {st.momentum ? fmtPct(st.momentum.total * 100) : "—"} · 回撤 {st.momentum ? fmtDD(st.momentum.max_dd * 100) : "—"}</span>
        <span>沪深300 {st.bench ? fmtPct(st.bench.total * 100) : "—"} · 回撤 {st.bench ? fmtDD(st.bench.max_dd * 100) : "—"}</span>
        <span>低估值：{pv.value_note ?? "需实盘运行（无历史估值数据，无法回测）"}</span>
      </div>
      {(latest.trend.length > 0 || latest.momentum.length > 0) && (
        <div className="mt-2 text-xs text-muted-foreground">
          最新目标：
          趋势跟踪 [{latest.trend.slice(0, 10).map((t) => t.name || t.code).join(" ")}]
          {" "}动量 [{latest.momentum.slice(0, 10).map((t) => t.name || t.code).join(" ")}]
        </div>
      )}
      <p className="mt-2 text-xs text-muted-foreground/80">
        {pv.caption ??
          "周末收盘后选股、下一交易日收盘价成交、等权、未计交易成本；股票池为当前市值前300，存在幸存者偏差和前视偏差。仅用于了解规则特点。"}
      </p>
      <Button variant="outline" size="sm" className="mt-2" disabled={busy}
              onClick={onEnable}>
        {busy ? "启用中…" : "启用内置选手"}
      </Button>
    </Card>
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
            <Button variant="outline"
                    disabled={busy || !canMutate}
                    title={canMutate ? "创建 3 个内置规则策略选手" : NEED_KEY}
                    onClick={enableHouse}>
              {busy ? "启用中…" : "启用内置选手"}
            </Button>
          )}
          <Button onClick={() => setRegOpen(true)}>
            报名 Agent
          </Button>
        </div>
      </div>

      <PageIntro page="arena" />
      {err != null && <ErrorBanner error={err} onRetry={load} />}
      {!err && !lb && <Skeleton rows={8} />}

      {lb && !hasHouse && (
        <PreviewCard busy={busy} onEnable={enableHouse} />
      )}

      {lb && rows.length === 0 && (
        <Card title="还没有 Agent 参赛">
          <EmptyState icon={Trophy} text="还没有 Agent 参赛" className="py-3" />
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
                <EmptyState text="净值曲线将在第二个交易日收盘后出现" className="py-10" />
              )}
          </Card>
          <Card title="排行榜" className="overflow-hidden">
            <div className="overflow-x-auto">
              <Table className="min-w-[640px]">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>#</TableHead>
                    <TableHead>Agent</TableHead>
                    <TableHead>模型</TableHead>
                    <TableHead className="num">收益</TableHead>
                    <TableHead className="num">超额<InfoTip term="超额收益" /></TableHead>
                    <TableHead className="num">回撤<InfoTip term="最大回撤" /></TableHead>
                    <TableHead className="num">夏普<InfoTip term="夏普" /></TableHead>
                    <TableHead className="num">交易</TableHead>
                    <TableHead className="num">胜率<InfoTip term="胜率" /></TableHead>
                    <TableHead>最近交易</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((a) => (
                    <TableRow key={a.id} className="hover:bg-muted/50">
                      <TableCell className="num"
                          style={{ color: topColors.get(a.id) }}>
                        {a.rank}
                      </TableCell>
                      <TableCell>
                        <Link to={`/arena/${a.id}`}
                              className="font-medium text-foreground hover:underline">
                          {a.name}
                        </Link>
                        {a.kind === "house" && (
                          <Badge className="ml-1.5 px-1.5 py-0 text-[10px]"
                                 title={HOUSE_DESC[a.id] ?? "内置规则策略"}>
                            内置
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {a.model
                          ? <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{a.model}</span>
                          : <span className="text-muted-foreground/60">—</span>}
                      </TableCell>
                      <TableCell className={`num ${signedClass(a.return)}`}>
                        {fmtPct(a.return * 100)}
                      </TableCell>
                      <TableCell className={`num ${signedClass(a.excess)}`}>
                        {a.excess == null ? "—" : fmtPct(a.excess * 100)}
                      </TableCell>
                      <TableCell className={`num ${ddClass(a.max_drawdown)}`}>
                        {fmtDD(a.max_drawdown * 100)}
                      </TableCell>
                      <TableCell className="num">
                        {a.sharpe == null ? "—" : a.sharpe.toFixed(2)}
                      </TableCell>
                      <TableCell className="num">{a.num_trades}</TableCell>
                      <TableCell className="num">
                        {a.win_rate == null ? "—" : `${(a.win_rate * 100).toFixed(0)}%`}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {a.last_trade_at?.slice(5, 16).replace("T", " ") ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
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
