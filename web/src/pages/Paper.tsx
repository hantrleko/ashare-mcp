import { useCallback, useEffect, useState } from "react";
import { LineSeries } from "lightweight-charts";
import { api, type Order, type PaperStatus, type Position, type Trigger, type EquityPoint } from "../api";
import { Card, ErrorBanner, PctText, Spinner, useChart } from "../components/ui";
import { fmtNum, fmtPrice, fmtSigned } from "../format";
import { useToast } from "../components/Toast";
import { SearchBox } from "../components/SearchBox";

export default function Paper() {
  const toast = useToast();
  const [st, setSt] = useState<PaperStatus | null>(null);
  const [pos, setPos] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [trigs, setTrigs] = useState<Trigger[]>([]);
  const [hist, setHist] = useState<EquityPoint[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [s, p, o, t, h] = await Promise.all([
        api.paperStatus(), api.paperPositions(), api.paperOrders(50),
        api.paperTriggers(), api.paperHistory(),
      ]);
      setSt(s); setPos(p.data); setOrders(o.data); setTrigs(t.data); setHist(h.data);
      setErr(null);
    } catch (e) { setErr(e); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const doSell = async (code: string) => {
    const p = pos.find((x) => x.code === code);
    if (!p) return;
    try {
      const r = await api.paperSell(code, p.available);
      toast("ok", `卖出成交 ${r.code} ${r.shares}股 @ ${r.price} · 盈亏${r.realized_pnl}`);
      load();
    } catch (e) { toast("err", `卖出失败：${e instanceof Error ? e.message : e}`); }
  };

  if (loading) return <Spinner label="加载账户…" />;

  return (
    <div className="space-y-4">
      <ErrorBanner error={err} onRetry={load} />
      <p className="text-xs text-slate-500">
        A股规则：1手=100股 · T+1 · 涨跌停校验 · 佣金万2.5(最低5元)+印花税万5(卖出)+过户费万0.1
      </p>

      {st && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Stat label="总资产" v={fmtNum(st.equity)} sub={<PctText v={st.total_return_pct} />} />
          <Stat label="现金" v={fmtNum(st.cash)} />
          <Stat label="持仓市值" v={fmtNum(st.market_value)} />
          <Stat label="总盈亏" v={fmtSigned(st.total_pnl)} cls={st.total_pnl >= 0 ? "text-up" : "text-down"} />
          <Stat label="持仓数" v={String(st.position_count)} />
        </div>
      )}

      <Card title="净值曲线">
        {hist.length > 1 ? <EquityChart pts={hist} /> : (
          <p className="py-4 text-center text-sm text-slate-500">暂无足够历史（每次刷新账户记录当日净值）</p>
        )}
      </Card>

      <Card title="持仓">
        {pos.length ? (
          <div className="overflow-x-auto">
            <table className="w-full whitespace-nowrap text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-slate-500">
                  {["代码", "名称", "持仓", "可卖(T+1)", "今日买入", "成本", "现价", "市值", "盈亏", ""].map((h) => (
                    <th key={h} className="px-2 py-1.5 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pos.map((p) => (
                  <tr key={p.code} className="border-b border-line/40">
                    <td className="num px-2 py-1.5">{p.code}</td>
                    <td className="px-2 py-1.5">{p.name}</td>
                    <td className="num px-2 py-1.5">{p.shares}</td>
                    <td className="num px-2 py-1.5">{p.available}</td>
                    <td className="num px-2 py-1.5 text-slate-400">{p.today_bought}</td>
                    <td className="num px-2 py-1.5">{fmtPrice(p.avg_cost, 3)}</td>
                    <td className="num px-2 py-1.5">{fmtPrice(p.last_price)}</td>
                    <td className="num px-2 py-1.5">{fmtNum(p.market_value)}</td>
                    <td className={`num px-2 py-1.5 ${p.pnl >= 0 ? "text-up" : "text-down"}`}>{fmtSigned(p.pnl)}</td>
                    <td className="px-2 py-1.5">
                      <button
                        onClick={() => doSell(p.code)}
                        disabled={p.available <= 0}
                        className="rounded border border-down/60 px-2 py-0.5 text-xs text-down hover:bg-down/20 disabled:opacity-30"
                      >
                        卖出全部可卖
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="py-4 text-center text-sm text-slate-500">暂无持仓（在个股页快捷交易下单）</p>}
      </Card>

      <TriggerPanel trigs={trigs} onChange={load} toast={toast} />

      <Card title="订单">
        {orders.length ? (
          <div className="max-h-80 overflow-x-auto">
            <table className="w-full whitespace-nowrap text-xs">
              <thead>
                <tr className="border-b border-line text-left text-slate-500">
                  {["时间", "代码", "名称", "方向", "股数", "价格", "金额", "费用", "实现盈亏", "状态"].map((h) => (
                    <th key={h} className="px-2 py-1.5 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id} className="border-b border-line/40">
                    <td className="num px-2 py-1.5 text-slate-400">{o.time.replace("T", " ")}</td>
                    <td className="num px-2 py-1.5">{o.symbol}</td>
                    <td className="px-2 py-1.5">{o.name}</td>
                    <td className={`px-2 py-1.5 ${o.side === "buy" ? "text-up" : "text-down"}`}>
                      {o.side === "buy" ? "买入" : "卖出"}
                    </td>
                    <td className="num px-2 py-1.5">{o.shares}</td>
                    <td className="num px-2 py-1.5">{fmtPrice(o.price)}</td>
                    <td className="num px-2 py-1.5">{fmtNum(o.amount)}</td>
                    <td className="num px-2 py-1.5">{o.fee.toFixed(2)}</td>
                    <td className="num px-2 py-1.5">{o.realized_pnl != null ? fmtSigned(o.realized_pnl) : "—"}</td>
                    <td className="px-2 py-1.5">{o.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="py-4 text-center text-sm text-slate-500">暂无订单</p>}
      </Card>

      <ResetCard onDone={() => { toast("ok", "账户已重置"); load(); }} />
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
    const s = chart.addSeries(LineSeries, { color: "#7b7ff2", lineWidth: 2 });
    s.setData(pts.map((p) => ({ time: p.date, value: p.equity })));
    chart.timeScale().fitContent();
  }, [chart, pts]);
  return <div ref={ref} className="w-full" />;
}

function TriggerPanel({ trigs, onChange, toast }: {
  trigs: Trigger[]; onChange: () => void;
  toast: (k: "ok" | "err", t: string) => void;
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
      const t = await api.paperAddTrigger({
        symbol: sym, side, shares, trigger_price: price, condition: cond, note: "",
      });
      toast("ok", `已添加条件单 #${t.id}`);
      onChange();
    } catch (e) { toast("err", `添加失败：${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };

  const check = async () => {
    try {
      const r = await api.paperCheck();
      toast("ok", `检查完成，待触发 ${r.pending} 个`);
      onChange();
    } catch (e) { toast("err", `检查失败：${e instanceof Error ? e.message : e}`); }
  };

  const cancel = async (id: string) => {
    try {
      await api.paperCancelTrigger(id);
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
      extra={<button onClick={check} className="rounded border border-line px-2 py-1 text-xs hover:border-slate-500">立即检查</button>}
    >
      <div className="mb-3 flex flex-wrap items-end gap-2 text-sm">
        <div className="w-56">
          <label className="mb-1 block text-xs text-slate-500">代码</label>
          <SearchBox onPick={(h) => setSym(h.code)} />
        </div>
        <input value={sym} onChange={(e) => setSym(e.target.value)} placeholder="600519"
          className="num w-24 rounded border border-line bg-panel2 px-2 py-1.5 outline-none" />
        <select value={side} onChange={(e) => setSide(e.target.value)}
          className="rounded border border-line bg-panel2 px-2 py-1.5">
          <option value="buy">买入</option><option value="sell">卖出</option>
        </select>
        <select value={cond} onChange={(e) => setCond(e.target.value)}
          className="rounded border border-line bg-panel2 px-2 py-1.5">
          <option value=">=">价格 ≥ 触发价</option><option value="<=">价格 ≤ 触发价</option>
        </select>
        <input type="number" step={0.01} value={price} onChange={(e) => setPrice(Number(e.target.value))}
          className="num w-24 rounded border border-line bg-panel2 px-2 py-1.5 outline-none" />
        <input type="number" step={100} min={100} value={shares}
          onChange={(e) => setShares(Number(e.target.value))}
          className="num w-24 rounded border border-line bg-panel2 px-2 py-1.5 outline-none" />
        <button onClick={add} disabled={busy || !sym.trim()}
          className="rounded bg-slate-700 px-3 py-1.5 hover:bg-slate-600 disabled:opacity-40">
          添加
        </button>
      </div>
      {trigs.length ? (
        <div className="overflow-x-auto">
          <table className="w-full whitespace-nowrap text-xs">
            <thead>
              <tr className="border-b border-line text-left text-slate-500">
                {["id", "代码", "方向", "条件", "触发价", "股数", "状态", "成交价", "创建时间", ""].map((h) => (
                  <th key={h} className="px-2 py-1.5 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trigs.map((t) => (
                <tr key={t.id} className="border-b border-line/40">
                  <td className="num px-2 py-1.5 text-slate-400">{t.id}</td>
                  <td className="num px-2 py-1.5">{t.symbol}</td>
                  <td className={`px-2 py-1.5 ${t.side === "buy" ? "text-up" : "text-down"}`}>
                    {t.side === "buy" ? "买入" : "卖出"}
                  </td>
                  <td className="px-2 py-1.5">{t.condition}</td>
                  <td className="num px-2 py-1.5">{fmtPrice(t.trigger_price)}</td>
                  <td className="num px-2 py-1.5">{t.shares}</td>
                  <td className="px-2 py-1.5">{badge(t.status)}{t.error ? <span className="ml-1 text-red-400">{t.error}</span> : null}</td>
                  <td className="num px-2 py-1.5">{t.filled_price != null ? fmtPrice(t.filled_price) : "—"}</td>
                  <td className="num px-2 py-1.5 text-slate-400">{t.created_at.replace("T", " ")}</td>
                  <td className="px-2 py-1.5">
                    {t.status === "pending" && (
                      <button onClick={() => cancel(t.id)}
                        className="rounded border border-line px-1.5 py-0.5 text-slate-400 hover:text-red-400">取消</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="py-3 text-sm text-slate-500">暂无条件单</p>}
    </Card>
  );
}

function ResetCard({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [cap, setCap] = useState(1_000_000);
  const reset = async () => {
    await api.paperReset(cap);
    setOpen(false);
    onDone();
  };
  return (
    <Card title="重置账户">
      {!open ? (
        <button onClick={() => setOpen(true)} className="rounded border border-red-800 px-3 py-1.5 text-sm text-red-400 hover:bg-red-950/40">
          重置账户（清空持仓与订单）
        </button>
      ) : (
        <div className="flex items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-slate-500">初始资金</label>
            <input type="number" step={100000} min={10000} value={cap}
              onChange={(e) => setCap(Number(e.target.value))}
              className="num rounded border border-line bg-panel2 px-2 py-1.5 outline-none" />
          </div>
          <button onClick={reset} className="rounded bg-red-800 px-3 py-1.5 text-sm text-white hover:bg-red-700">确认重置</button>
          <button onClick={() => setOpen(false)} className="rounded border border-line px-3 py-1.5 text-sm">取消</button>
        </div>
      )}
    </Card>
  );
}
