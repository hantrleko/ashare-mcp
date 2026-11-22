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
  mkt_cap?: number | null; float_mkt_cap?: number | null;
  date?: string; time?: string; note?: string;
}

export interface Bar {
  date: string; open: number; high: number; low: number;
  close: number; volume: number; amount?: number; pct_chg?: number;
}

export interface SearchHit { code: string; name: string; market: string }

export interface IntradayPoint { time: string; price: number; volume: number }
export interface IntradayData {
  symbol: string; mode: "intraday" | "daily";
  prev_close: number | null; points: IntradayPoint[];
}

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

export interface AccountInfo {
  id: string; name: string; created_at: string; updated_at: string;
  initial_capital: number | null; cash: number | null;
  last_equity: number | null; position_count: number;
}

export interface SchedulerStatus {
  enabled: boolean;
  last_trigger_check: string | null;
  last_settlement_date: string | null;
  last_error: string | null;
}

export interface BreadthDist { range: string; count: number }
export interface OverviewData {
  indices?: Quote[];
  breadth?: {
    advance?: number; decline?: number; flat?: number;
    avg_pct_chg?: number; total_amount_yi?: number;
    distribution?: BreadthDist[];
    limit_up?: number; limit_down?: number;
  };
}

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
  monthly_returns: { month: string; ret: number }[];
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
  intraday: (sym: string) =>
    req<Resp<IntradayData>>(`/intraday/${enc(sym)}`),
  overview: () => req<Resp<OverviewData>>("/overview"),
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

  accounts: () => req<{ data: AccountInfo[] }>("/accounts"),
  accountCreate: (name: string, capital: number, id?: string) =>
    req<AccountInfo>("/accounts", post({ name, capital, ...(id ? { id } : {}) })),
  accountRename: (id: string, name: string) =>
    req<AccountInfo>(`/accounts/${enc(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  accountDelete: (id: string) =>
    req<Record<string, unknown>>(`/accounts/${enc(id)}`, { method: "DELETE" }),
  scheduler: () => req<SchedulerStatus>("/scheduler"),

  paperStatus: (account: string) =>
    req<PaperStatus>(`/paper/status?account=${enc(account)}`),
  paperPositions: (account: string) =>
    req<{ data: Position[] }>(`/paper/positions?account=${enc(account)}`),
  paperOrders: (account: string, limit = 50) =>
    req<{ data: Order[] }>(`/paper/orders?limit=${limit}&account=${enc(account)}`),
  paperTriggers: (account: string) =>
    req<{ data: Trigger[] }>(`/paper/triggers?account=${enc(account)}`),
  paperHistory: (account: string) =>
    req<{ data: EquityPoint[] }>(`/paper/history?account=${enc(account)}`),
  paperBuy: (account: string, symbol: string, shares: number) =>
    req<Record<string, unknown>>(`/paper/buy?account=${enc(account)}`,
      post({ symbol, shares })),
  paperSell: (account: string, symbol: string, shares: number) =>
    req<Record<string, unknown>>(`/paper/sell?account=${enc(account)}`,
      post({ symbol, shares })),
  paperAddTrigger: (account: string,
                    t: Omit<Trigger, "id" | "created_at" | "status">) =>
    req<Trigger>(`/paper/triggers?account=${enc(account)}`, post(t)),
  paperCancelTrigger: (account: string, id: string) =>
    req<Trigger>(`/paper/triggers/${enc(id)}?account=${enc(account)}`,
      { method: "DELETE" }),
  paperCheck: (account: string) =>
    req<{ triggers: Trigger[]; pending: number }>(
      `/paper/check?account=${enc(account)}`, { method: "POST" }),
  paperReset: (account: string, capital: number) =>
    req<Record<string, unknown>>(`/paper/reset?account=${enc(account)}`,
      post({ capital })),

  backtest: (b: BacktestIn) => req<BacktestResult>("/backtest", post(b)),
};

function post(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
