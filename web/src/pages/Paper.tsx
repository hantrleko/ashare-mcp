import { useCallback, useEffect, useState } from "react";
import { LineSeries } from "lightweight-charts";
import { api, ApiError, type Order, type PaperStatus, type Position, type Trigger, type EquityPoint, type SchedulerStatus } from "../api";
import { Card, EmptyState, ErrorBanner, PctText, Spinner } from "../components/ui";
import { useChart } from "../components/chart";
import { fmtNum, fmtPrice, fmtSigned, signedClass } from "../format";
import { useToast } from "../components/Toast";
import { SearchBox } from "../components/SearchBox";
import { useAccount } from "../account";
import { NEED_KEY, useCanMutate } from "../auth";
import { Inbox, LineChart, ListOrdered, Timer } from "lucide-react";
import { cssVar, onThemeChange } from "../theme";
import { SERIES } from "../lib/palette";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { PageIntro } from "../components/Intro";
import { InfoTip } from "../components/InfoTip";
import { DemoButton } from "../components/Demo";

export default function Paper() {
  const toast = useToast();
  const canMutate = useCanMutate();
  const { account, accounts, setAccount, refresh } = useAccount();
  const [st, setSt] = useState<PaperStatus | null>(null);
  const [pos, setPos] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [trigs, setTrigs] = useState<Trigger[]>([]);
  const [hist, setHist] = useState<EquityPoint[]>([]);
  const [sched, setSched] = useState<SchedulerStatus | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [s, p, o, t, h] = await Promise.all([
        api.paperStatus(account), api.paperPositions(account),
        api.paperOrders(account, 50),
        api.paperTriggers(account), api.paperHistory(account),
      ]);
      setSt(s); setPos(p.data); setOrders(o.data); setTrigs(t.data); setHist(h.data);
      setErr(null);
    } catch (e) { setErr(e); }
    finally { setLoading(false); }
  }, [account]);
  useEffect(() => { setLoading(true); load(); }, [load]);
  useEffect(() => {
    api.scheduler().then(setSched).catch(() => {});
  }, []);

  const doSell = async (code: string) => {
    const p = pos.find((x) => x.code === code);
    if (!p) return;
    try {
      const r = await api.paperSell(account, code, p.available);
      toast("ok", `卖出成交 ${r.code} ${r.shares}股 @ ${r.price} · 盈亏${r.realized_pnl}`);
      load();
    } catch (e) { toast("err", `卖出失败：${e instanceof Error ? e.message : e}`); }
  };

  const cur = accounts.find((a) => a.id === account);

  if (loading) return <Spinner label="加载账户…" />;

  return (
    <div className="space-y-4">
      <PageIntro page="paper" />
      <ErrorBanner error={err} onRetry={load} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500">
          A股规则：1手=100股 · T+1<InfoTip term="T+1" /> · 涨跌停校验 · 佣金万2.5(最低5元)+印花税万5(卖出)+过户费万0.1
        </p>
        <AccountHeader
          name={cur?.name ?? account}
          isDefault={account === "default"}
          canMutate={canMutate}
          onRenamed={async (name) => {
            await api.accountRename(account, name);
            await refresh();
            toast("ok", "已重命名");
          }}
          onDeleted={async () => {
            await api.accountDelete(account);
            await refresh();
            setAccount("default");
            toast("ok", "账户已删除");
          }}
          onError={(m) => toast("err", m)}
        />
      </div>

      {st && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Stat label="总资产" v={fmtNum(st.equity)} sub={<PctText v={st.total_return_pct} />} />
          <Stat label="现金" v={fmtNum(st.cash)} />
          <Stat label="持仓市值" v={fmtNum(st.market_value)} />
          <Stat label="总盈亏" v={fmtSigned(st.total_pnl)} cls={signedClass(st.total_pnl)} />
          <Stat label="持仓数" v={String(st.position_count)} />
        </div>
      )}

      <Card title="净值曲线">
        {hist.length > 1 ? <EquityChart pts={hist} /> : (
          <EmptyState icon={LineChart} text="暂无足够历史（每次刷新账户记录当日净值）" />
        )}
      </Card>

      <Card title="持仓">
        {pos.length ? (
          <div className="flex flex-col gap-4 md:flex-row">
          <AllocationDonut pos={pos} cash={st?.cash ?? 0} />
          <div className="min-w-0 flex-1 overflow-x-auto">
            <Table className="whitespace-nowrap">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  {["代码", "名称", "持仓", "可卖(T+1)", "今日买入", "成本", "现价", "市值", "盈亏", ""].map((h) => (
                    <TableHead key={h}>{h}{h === "可卖(T+1)" && <InfoTip term="T+1" />}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {pos.map((p) => (
                  <TableRow key={p.code} className="hover:bg-muted/50">
                    <TableCell className="num">{p.code}</TableCell>
                    <TableCell>{p.name}</TableCell>
                    <TableCell className="num">{p.shares}</TableCell>
                    <TableCell className="num">{p.available}</TableCell>
                    <TableCell className="num text-muted-foreground">{p.today_bought}</TableCell>
                    <TableCell className="num">{fmtPrice(p.avg_cost, 3)}</TableCell>
                    <TableCell className="num">{fmtPrice(p.last_price)}</TableCell>
                    <TableCell className="num">{fmtNum(p.market_value)}</TableCell>
                    <TableCell className={`num ${signedClass(p.pnl)}`}>{fmtSigned(p.pnl)}</TableCell>
                    <TableCell>
                      <Button
                        variant="destructive" size="sm"
                        onClick={() => doSell(p.code)}
                        disabled={p.available <= 0 || !canMutate}
                        title={canMutate ? "" : NEED_KEY}
                      >
                        卖出全部可卖
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          </div>
        ) : <EmptyState icon={Inbox} text="暂无持仓（在个股页快捷交易下单）" />}
      </Card>

      {!pos.length && !orders.length && (
        <Card>
          <EmptyState icon={Inbox} text="账户还没有任何交易，可以从一个示例账户开始体验" />
          <div className="mt-3 text-center"><DemoButton /></div>
        </Card>
      )}

      <TriggerPanel account={account} trigs={trigs} sched={sched}
                    onChange={load} toast={toast} canMutate={canMutate} />

      <Card title="订单">
        {orders.length ? (
          <div className="max-h-80 overflow-x-auto">
            <Table className="whitespace-nowrap text-xs">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  {["时间", "代码", "名称", "方向", "股数", "价格", "金额", "费用", "实现盈亏", "状态"].map((h) => (
                    <TableHead key={h}>
                      {h}{h === "状态" && <InfoTip term="被拦截订单" />}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {orders.map((o) => (
                  <TableRow key={o.id} className="hover:bg-muted/50">
                    <TableCell className="num text-muted-foreground">{o.time.replace("T", " ")}</TableCell>
                    <TableCell className="num">{o.symbol}</TableCell>
                    <TableCell>{o.name}</TableCell>
                    <TableCell className={o.side === "buy" ? "text-up" : "text-down"}>
                      {o.side === "buy" ? "买入" : "卖出"}
                    </TableCell>
                    <TableCell className="num">{o.shares}</TableCell>
                    <TableCell className="num">{fmtPrice(o.price)}</TableCell>
                    <TableCell className="num">{fmtNum(o.amount)}</TableCell>
                    <TableCell className="num">{o.fee.toFixed(2)}</TableCell>
                    <TableCell className="num">{o.realized_pnl != null ? fmtSigned(o.realized_pnl) : "—"}</TableCell>
                    <TableCell>{o.status}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : <EmptyState icon={ListOrdered} text="暂无订单" />}
      </Card>

      <ResetCard account={account} canMutate={canMutate}
                 onDone={() => { toast("ok", "账户已重置"); load(); }} />
    </div>
  );
}

function AccountHeader({ name, isDefault, canMutate = true, onRenamed, onDeleted, onError }: {
  name: string; isDefault: boolean; canMutate?: boolean;
  onRenamed: (name: string) => Promise<void>;
  onDeleted: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const [val, setVal] = useState(name);
  useEffect(() => setVal(name), [name]);

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-slate-500">当前账户</span>
      {renaming ? (
        <>
          <Input autoFocus value={val} onChange={(e) => setVal(e.target.value)}
                 className="w-32" />
          <Button variant="outline" size="sm"
            onClick={async () => {
              try { await onRenamed(val.trim()); setRenaming(false); }
              catch (e) { onError(e instanceof ApiError ? e.message : String(e)); }
            }}>保存</Button>
          <Button variant="ghost" size="sm" onClick={() => setRenaming(false)}>取消</Button>
        </>
      ) : (
        <>
          <span className="font-medium text-foreground">{name}</span>
          <Button variant="outline" size="sm" onClick={() => setRenaming(true)} disabled={!canMutate}
                  title={canMutate ? "" : NEED_KEY}>重命名</Button>
          {!isDefault && (
            confirmDel ? (
              <>
                <span className="text-xs text-up">确认删除？数据不可恢复</span>
                <Button variant="destructive" size="sm"
                  onClick={async () => {
                    try { await onDeleted(); }
                    catch (e) { onError(e instanceof ApiError ? e.message : String(e)); }
                    setConfirmDel(false);
                  }}>确认删除</Button>
                <Button variant="outline" size="sm" onClick={() => setConfirmDel(false)}>取消</Button>
              </>
            ) : (
              <Button variant="outline" size="sm" onClick={() => setConfirmDel(true)} disabled={!canMutate}
                      title={canMutate ? "" : NEED_KEY}
                      className="border-red-800/60 text-red-400 hover:bg-red-950/40 hover:text-red-300">删除</Button>
            )
          )}
        </>
      )}
    </div>
  );
}

const SLICE_COLORS = SERIES;

function AllocationDonut({ pos, cash }: { pos: Position[]; cash: number }) {
  const slices = [
    ...pos.map((p, i) => ({
      label: p.name || p.code, v: p.market_value,
      color: SLICE_COLORS[i % SLICE_COLORS.length],
    })),
    { label: "现金", v: Math.max(cash, 0), color: "#475569" },
  ].filter((s) => s.v > 0);
  const total = slices.reduce((a, s) => a + s.v, 0) || 1;
  let acc = -Math.PI / 2;
  const R = 46, r = 26, CX = 60, CY = 60;
  const arcs = slices.map((s) => {
    const a0 = acc;
    const a1 = acc + (s.v / total) * Math.PI * 2;
    acc = a1;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const p = (a: number, rr: number) =>
      `${CX + rr * Math.cos(a)},${CY + rr * Math.sin(a)}`;
    return {
      ...s,
      d: `M${p(a0, R)} A${R} ${R} 0 ${large} 1 ${p(a1, R)} ` +
         `L${p(a1, r)} A${r} ${r} 0 ${large} 0 ${p(a0, r)} Z`,
      pct: (s.v / total) * 100,
    };
  });
  return (
    <div className="flex items-center gap-4 md:w-64">
      <svg viewBox="0 0 120 120" className="h-28 w-28 shrink-0">
        {arcs.map((a) => (
          <path key={a.label} d={a.d} fill={a.color} opacity={0.9} />
        ))}
      </svg>
      <div className="space-y-1 text-xs">
        {arcs.map((a) => (
          <div key={a.label} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm" style={{ background: a.color }} />
            <span className="text-slate-400">{a.label}</span>
            <span className="num ml-auto pl-2">{a.pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, v, cls = "", sub }: { label: string; v: string; cls?: string; sub?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-panel px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`num text-lg font-medium ${cls}`}>{v}</div>
      {sub}
    </div>
  );
}

function EquityChart({ pts }: { pts: EquityPoint[] }) {
  const { ref, chart } = useChart({ height: 220 });
  useEffect(() => {
    if (!chart) return;
    const s = chart.addSeries(LineSeries, {
      color: cssVar("--color-accent"), lineWidth: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      // keep a sensible ±0.5% window when equity is flat
      autoscaleInfoProvider: (orig: () => { priceRange: { minValue: number; maxValue: number } } | null) => { // eslint-disable-line @typescript-eslint/no-explicit-any
        const r = orig();
        if (!r) return r;
        const mid = (r.priceRange.minValue + r.priceRange.maxValue) / 2;
        const half = Math.max(mid * 0.005, 1);
        r.priceRange = { minValue: mid - half, maxValue: mid + half };
        return r;
      },
    });
    s.setData(pts.map((p) => ({ time: (p.date || "").slice(0, 10), value: p.equity })));
    chart.timeScale().fitContent();
    const off = onThemeChange(() =>
      s.applyOptions({ color: cssVar("--color-accent") }));
    return () => off();
  }, [chart, pts]);
  return <div ref={ref} className="w-full min-w-0 overflow-hidden" />;
}

function TriggerPanel({ account, trigs, sched, onChange, toast, canMutate = true }: {
  account: string; trigs: Trigger[]; sched: SchedulerStatus | null;
  onChange: () => void;
  toast: (k: "ok" | "err", t: string) => void;
  canMutate?: boolean;
}) {
  const [sym, setSym] = useState("");
  const [side, setSide] = useState("buy");
  const [shares, setShares] = useState(100);
  const [cond, setCond] = useState(">=");
  const [price, setPrice] = useState(10);
  const [busy, setBusy] = useState(false);

  const add = async () => {
    setBusy(true);
    try {
      const t = await api.paperAddTrigger(account, {
        symbol: sym, side, shares, trigger_price: price, condition: cond, note: "",
      });
      toast("ok", `已添加条件单 #${t.id}`);
      onChange();
    } catch (e) { toast("err", `添加失败：${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };

  const check = async () => {
    try {
      const r = await api.paperCheck(account);
      toast("ok", `检查完成，待触发 ${r.pending} 个`);
      onChange();
    } catch (e) { toast("err", `检查失败：${e instanceof Error ? e.message : e}`); }
  };

  const cancel = async (id: string) => {
    try {
      await api.paperCancelTrigger(account, id);
      toast("ok", `已取消 ${id}`);
      onChange();
    } catch (e) { toast("err", `取消失败：${e instanceof Error ? e.message : e}`); }
  };

  const badge = (s: string) => {
    const m: Record<string, string> = {
      pending: "border-amber-700 text-amber-400",
      filled: "border-emerald-700 text-emerald-400",
      failed: "border-red-700 text-red-400",
      cancelled: "border-slate-600 text-slate-500",
      filling: "border-sky-700 text-sky-400",
    };
    const cn: Record<string, string> = {
      pending: "待触发", filled: "已成交", failed: "失败", cancelled: "已取消", filling: "成交中",
    };
    return <span className={`rounded border px-1.5 py-0.5 text-xs ${m[s] ?? m.pending}`}>{cn[s] ?? s}</span>;
  };

  return (
    <Card
      title="条件单"
      extra={<Button variant="outline" size="sm" onClick={check}>立即检查</Button>}
    >
      <p className="mb-2 text-xs text-slate-500">
        {sched?.enabled
          ? `盘中每分钟自动检查条件单 · 上次检查 ${sched.last_trigger_check ?? "—"}`
          : "自动检查未启用，查看账户时检查"}
      </p>
      <div className="mb-3 flex flex-wrap items-end gap-2 text-sm">
        <div className="w-56">
          <Label>代码</Label>
          <SearchBox onPick={(h) => setSym(h.code)} />
        </div>
        <Input value={sym} onChange={(e) => setSym(e.target.value)} placeholder="600519"
          className="num w-24" />
        <Select value={side} onChange={(e) => setSide(e.target.value)}>
          <option value="buy">买入</option><option value="sell">卖出</option>
        </Select>
        <Select value={cond} onChange={(e) => setCond(e.target.value)}>
          <option value=">=">价格 ≥ 触发价</option><option value="<=">价格 ≤ 触发价</option>
        </Select>
        <Input type="number" step={0.01} value={price} onChange={(e) => setPrice(Number(e.target.value))}
          className="num w-24" />
        <Input type="number" step={100} min={100} value={shares}
          onChange={(e) => setShares(Number(e.target.value))}
          className="num w-24" />
        <Button onClick={add} disabled={busy || !sym.trim() || !canMutate}
          title={canMutate ? "" : NEED_KEY}>
          添加
        </Button>
      </div>
      {trigs.length ? (
        <div className="overflow-x-auto">
          <Table className="whitespace-nowrap text-xs">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                {["id", "代码", "方向", "条件", "触发价", "股数", "状态", "成交价", "创建时间", ""].map((h) => (
                  <TableHead key={h}>{h}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {trigs.map((t) => (
                <TableRow key={t.id} className="hover:bg-muted/50">
                  <TableCell className="num text-muted-foreground">{t.id}</TableCell>
                  <TableCell className="num">{t.symbol}</TableCell>
                  <TableCell className={t.side === "buy" ? "text-up" : "text-down"}>
                    {t.side === "buy" ? "买入" : "卖出"}
                  </TableCell>
                  <TableCell>{t.condition}</TableCell>
                  <TableCell className="num">{fmtPrice(t.trigger_price)}</TableCell>
                  <TableCell className="num">{t.shares}</TableCell>
                  <TableCell>{badge(t.status)}{t.error ? <span className="ml-1 text-red-400">{t.error}</span> : null}</TableCell>
                  <TableCell className="num">{t.filled_price != null ? fmtPrice(t.filled_price) : "—"}</TableCell>
                  <TableCell className="num text-muted-foreground">{t.created_at.replace("T", " ")}</TableCell>
                  <TableCell>
                    {t.status === "pending" && (
                      <Button variant="ghost" size="sm" onClick={() => cancel(t.id)}
                        className="h-6 px-1.5 text-muted-foreground hover:text-red-400">取消</Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : <EmptyState icon={Timer} text="暂无条件单" className="py-3" />}
    </Card>
  );
}

function ResetCard({ account, canMutate = true, onDone }: {
  account: string; canMutate?: boolean; onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [cap, setCap] = useState(1_000_000);
  const reset = async () => {
    await api.paperReset(account, cap);
    setOpen(false);
    onDone();
  };
  return (
    <Card title="重置账户">
      {!open ? (
        <Button variant="outline" onClick={() => setOpen(true)} disabled={!canMutate}
          title={canMutate ? "" : NEED_KEY}
          className="border-red-800/60 text-red-400 hover:bg-red-950/40 hover:text-red-300">
          重置账户（清空持仓与订单）
        </Button>
      ) : (
        <div className="flex items-end gap-3">
          <div>
            <Label>初始资金</Label>
            <Input type="number" step={100000} min={10000} value={cap}
              onChange={(e) => setCap(Number(e.target.value))}
              className="num" />
          </div>
          <Button variant="destructive" onClick={reset}>确认重置</Button>
          <Button variant="outline" onClick={() => setOpen(false)}>取消</Button>
        </div>
      )}
    </Card>
  );
}
