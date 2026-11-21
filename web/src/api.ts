/** Typed API client for the ashare-mcp web backend. */

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "网络错误：无法连接后端 (ashare_mcp.web 未启动?)");
  }
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* keep status text */ }
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

export interface Resp<T> { data: T; source?: string }

export interface Quote {
  code?: string; symbol?: string; name?: string;
  price?: number; prev_close?: number; open?: number; high?: number;
  low?: number; volume?: number; amount?: number; pct_chg?: number;
  change?: number; turnover?: number; pe_ttm?: number | null; pb?: number | null;
  date?: string; time?: string; note?: string;
}

export interface Bar {
  date: string; open: number; high: number; low: number;
  close: number; volume: number; amount?: number; pct_chg?: number;
}

export interface SearchHit { code: string; name: string; market: string }

export interface PaperStatus {
  cash: number; market_value: number; equity: number;
  initial_capital: number; total_pnl: number;
  total_return_pct: number | null; position_count: number;
}

export interface Position {
  code: string; name: string; shares: number; available: number;
  today_bought: number; avg_cost: number; last_price: number;
  market_value: number; pnl: number;
}

export interface Order {
  id: string; time: string; symbol: string; name?: string; side: string;
  shares: number; price: number; amount: number; fee: number;
  realized_pnl?: number; status: string;
}

export interface Trigger {
  id: string; symbol: string; side: string; shares: number;
  condition: string; trigger_price: number; note?: string;
  created_at: string; status: string;
  filled_price?: number; filled_at?: string; error?: string;
}

export interface EquityPoint { date: string; equity: number }

export interface Trade {
  date: string; side: string; price: number; shares: number;
  amount: number; fee: number; pnl?: number;
}

export interface BacktestResult {
  symbol: string; strategy: string; source?: string;
  start: string; end: string; capital: number; bars: number;
  final_equity: number; total_return: number; annual_return: number;
  max_drawdown: number; sharpe: number; num_trades: number;
  num_sells: number; win_rate: number | null;
  equity_curve: EquityPoint[]; benchmark: EquityPoint[];
  trades: Trade[];
}

export interface BacktestIn {
  symbol: string; strategy: string; params: Record<string, number | null>;
  start: string; end: string; capital: number;
  slippage_bps: number; min_trade_value: number;
}

const enc = encodeURIComponent;

export const api = {
  health: () => req<{ status: string }>("/health"),
  search: (q: string, limit = 10) =>
    req<Resp<SearchHit[]>>(`/search?q=${enc(q)}&limit=${limit}`),
  quote: (sym: string) => req<Resp<Quote>>(`/quote/${enc(sym)}`),
  quotes: (syms: string[]) => req<Resp<Quote[]>>(`/quotes?symbols=${syms.join(",")}`),
  kline: (sym: string, period = "daily", start = "", end = "", adjust = "qfq") =>
    req<Resp<Bar[]>>(`/kline/${enc(sym)}?period=${period}&start=${start}&end=${end}&adjust=${adjust}`),
  indices: () => req<Resp<Quote[]>>("/indices"),
  overview: () => req<Resp<Record<string, unknown>>>("/overview"),
  limitPool: (pool: string, date: string) =>
    req<Resp<Record<string, unknown>[]>>(`/limit-pool?pool=${pool}&date=${date}`),
  moneyFlow: (sym: string, days = 30) =>
    req<Resp<Record<string, unknown>[]>>(`/money-flow/${enc(sym)}?days=${days}`),
  financial: (sym: string, indicator = "按报告期") =>
    req<Resp<Record<string, unknown>[]>>(`/financial/${enc(sym)}?indicator=${enc(indicator)}`),
  statement: (sym: string, type: string) =>
    req<Resp<Record<string, unknown>[]>>(`/statement/${enc(sym)}?type=${type}`),
  factor: (sym: string) => req<Resp<Record<string, unknown>>>(`/factor/${enc(sym)}`),
  announcements: (symbol: string, date: string) =>
    req<Resp<Record<string, unknown>[]>>(`/announcements?symbol=${enc(symbol)}&date=${date}`),
  earnings: (reportDate: string, kind: string) =>
    req<Resp<Record<string, unknown>[]>>(`/earnings?report_date=${reportDate}&kind=${kind}`),

  paperStatus: () => req<PaperStatus>("/paper/status"),
  paperPositions: () => req<{ data: Position[] }>("/paper/positions"),
  paperOrders: (limit = 50) => req<{ data: Order[] }>(`/paper/orders?limit=${limit}`),
  paperTriggers: () => req<{ data: Trigger[] }>("/paper/triggers"),
  paperHistory: () => req<{ data: EquityPoint[] }>("/paper/history"),
  paperBuy: (symbol: string, shares: number) =>
    req<Record<string, unknown>>("/paper/buy", post({ symbol, shares })),
  paperSell: (symbol: string, shares: number) =>
    req<Record<string, unknown>>("/paper/sell", post({ symbol, shares })),
  paperAddTrigger: (t: Omit<Trigger, "id" | "created_at" | "status">) =>
    req<Trigger>("/paper/triggers", post(t)),
  paperCancelTrigger: (id: string) =>
    req<Trigger>(`/paper/triggers/${enc(id)}`, { method: "DELETE" }),
  paperCheck: () => req<{ triggers: Trigger[]; pending: number }>("/paper/check", { method: "POST" }),
  paperReset: (capital: number) => req<Record<string, unknown>>("/paper/reset", post({ capital })),

  backtest: (b: BacktestIn) => req<BacktestResult>("/backtest", post(b)),
};

function post(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
