/** Typed API client for the ashare-mcp web backend. */

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

const KEY_LS = "ashare.key";

export function getApiKey(): string {
  try { return localStorage.getItem(KEY_LS) ?? ""; } catch { return ""; }
}
export function setApiKey(k: string) {
  try {
    if (k) localStorage.setItem(KEY_LS, k.trim());
    else localStorage.removeItem(KEY_LS);
  } catch { /* private mode */ }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const key = getApiKey();
  const headers = new Headers(init?.headers);
  if (key) headers.set("Authorization", `Bearer ${key}`);
  let r: Response;
  try {
    r = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "网络错误：无法连接后端 (ashare_mcp.web 未启动?)");
  }
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* keep status text */ }
    if (r.status === 401) detail = `未授权 — 请在右上角 🔑 填入有效的 API Key（${detail}）`;
    else if (r.status === 403) detail = `无权操作 — ${detail}`;
    else if (r.status === 429) {
      const wait = r.headers.get("Retry-After");
      detail = `请求过于频繁，请 ${wait || "稍"} 秒后重试`;
    }
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
  realized_pnl?: number; status: string; reason?: string;
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

export interface PortfolioIn {
  symbols: string[]; weighting: string; rebalance: string;
  start: string; end: string; capital: number;
  slippage_bps: number; min_trade_value: number; benchmark: string;
}
export interface Holding { code: string; name: string; shares: number; value: number; weight: number | null }
export interface PortfolioResult {
  symbols: string[]; skipped_symbols: string[];
  weighting: string; rebalance: string; benchmark: string;
  start: string; end: string; capital: number; bars: number;
  final_equity: number; total_return: number; annual_return: number;
  max_drawdown: number; sharpe: number; num_trades: number;
  benchmark_total_return: number; benchmark_annual_return: number;
  benchmark_max_drawdown: number; excess_annual: number;
  annual_turnover: number | null; num_rebalances: number;
  blocked_orders: number;
  equity_curve: { date: string; equity: number; benchmark: number }[];
  monthly_returns: { month: string; ret: number }[];
  contribution: { code: string; name: string; pnl: number }[];
  final_holdings: Holding[];
  rebalance_log: { date: string; orders: number; turnover: number }[];
  trades: { date: string; symbol: string; side: string; price: number;
            shares: number; amount: number; fee: number; pnl?: number }[];
  notes: string[];
}
export interface ScanIn {
  symbol: string; strategy: string; grid: Record<string, number[]>;
  start: string; end: string; split: number; metric: string;
  capital: number; slippage_bps: number; min_trade_value: number;
}
export interface ScanMetrics {
  total_return: number; annual_return: number; sharpe: number;
  max_drawdown: number; num_trades: number;
}
export interface ScanResult {
  symbol: string; strategy: string; metric: string;
  split: number; split_date: string; bars: number; capital: number;
  results: { params: Record<string, number>; is: ScanMetrics; oos: ScanMetrics }[];
  skipped: Record<string, number>[];
  best_is: { params: Record<string, number>; is: ScanMetrics; oos: ScanMetrics };
  oos_rank_of_best_is: number; num_combos: number;
  axes?: { names: string[]; values: Record<string, number[]> };
  notes: string[];
}

export interface ScreenIn {
  ranges?: Record<string, [number | null, number | null]>;
  industries?: string[];
  boards?: string[];
  exclude_st?: boolean;
  exclude_suspended?: boolean;
  momentum?: Record<string, [number | null, number | null]>;
  sort_by?: string;
  desc?: boolean;
  limit?: number;
}
export interface ScreenRow {
  code: string; name: string; industry: string; board: string;
  price?: number | null; pct_chg?: number | null; turnover?: number | null;
  pe_ttm?: number | null; pb?: number | null; roe_est?: number | null;
  mkt_cap?: number | null; float_mkt_cap?: number | null;
  amount?: number | null; volume_ratio?: number | null;
  mom_20?: number | null; mom_60?: number | null;
}
export interface ScreenResult {
  total_universe: number; matched: number; rows: ScreenRow[];
  as_of: string; notes: string[];
}
export interface IndustryInfo { name: string; count: number }

export interface PeerRow {
  code: string; name: string; is_me: boolean;
  price?: number | null; pct_chg?: number | null;
  pe_ttm?: number | null; pb?: number | null;
  roe_est?: number | null; mkt_cap?: number | null;
  turnover?: number | null;
}
export interface PeersResult {
  industry: string; count: number;
  stock: PeerRow & { industry?: string;
    percentiles: Record<string, number | null> };
  peers: PeerRow[];
  medians: Record<string, number | null>;
}

export interface AuthMe {
  public: boolean; role: "admin" | "agent" | "anonymous";
  account: string | null;
}

export interface ArenaRow {
  id: string; name: string; model: string; rank: number;
  kind?: string;
  equity: number; initial_capital: number; return: number;
  excess: number | null; max_drawdown: number; sharpe: number | null;
  num_trades: number; win_rate: number | null; turnover: number;
  last_trade_at: string | null; days_active: number; position_count: number;
}
export interface ArenaLeaderboard {
  as_of: string; benchmark: string; agents: ArenaRow[];
  series: Record<string, EquityPoint[]>;
  bench_series: { date: string; close: number }[];
}
export interface ArenaDetail extends ArenaRow {
  created_at: string | null;
  kind?: string;
  series: { date: string; equity: number; benchmark: number | null }[];
  positions: { code: string; name: string; shares: number;
               avg_cost: number; last_price: number; market_value: number;
               pnl: number }[];
  trades: Order[];
  benchmark: string;
}

export interface HousePlan {
  plan_date: string; exec_date: string | null; status: string;
  targets: { code: string; name: string; rank: number;
             metrics?: Record<string, number>;
             note?: string }[];
  log: { action: string; code?: string; shares?: number;
         ok?: boolean; error?: string }[];
}
export interface HouseEnableResult {
  created: string[]; agents: string[];
  plans: Record<string, HousePlan>;
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
  marketClock: () =>
    req<{ date: string; server_time: string; is_trading_day: boolean | null }>("/market-clock"),

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
  paperBuy: (account: string, symbol: string, shares: number,
             reason = "") =>
    req<Record<string, unknown>>(`/paper/buy?account=${enc(account)}`,
      post({ symbol, shares, reason })),
  paperSell: (account: string, symbol: string, shares: number,
              reason = "") =>
    req<Record<string, unknown>>(`/paper/sell?account=${enc(account)}`,
      post({ symbol, shares, reason })),
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
  backtestPortfolio: (b: PortfolioIn) =>
    req<PortfolioResult>("/backtest/portfolio", post(b)),
  backtestScan: (b: ScanIn) => req<ScanResult>("/backtest/scan", post(b)),

  screen: (b: ScreenIn) => req<ScreenResult>("/screen", post(b)),
  peers: (sym: string, limit = 30) =>
    req<PeersResult>(`/peers/${enc(sym)}?limit=${limit}`),
  industries: () => req<{ data: IndustryInfo[] }>("/industries"),

  authMe: () => req<AuthMe>("/auth/me"),
  arenaLeaderboard: (benchmark = "sh000300") =>
    req<ArenaLeaderboard>(`/arena/leaderboard?benchmark=${enc(benchmark)}`),
  arenaAgent: (id: string, benchmark = "sh000300") =>
    req<ArenaDetail>(`/arena/agents/${enc(id)}?benchmark=${enc(benchmark)}`),
  arenaRegister: (b: { name: string; model?: string; capital?: number;
                       id?: string }) =>
    req<{ account: { id: string; name: string }; api_key: string }>(
      "/arena/agents", post(b)),
  arenaNewKey: (id: string) =>
    req<{ api_key: string }>(`/arena/agents/${enc(id)}/keys`, post({})),
  arenaRevoke: (id: string) =>
    req<{ revoked: number }>(`/arena/agents/${enc(id)}/keys/revoke`,
      post({})),
  houseEnable: () => req<HouseEnableResult>("/arena/house/enable", post({})),
  houseRun: (action: "plan" | "execute", force = false) =>
    req<Record<string, HousePlan>>("/arena/house/run",
      post({ action, force })),
  housePlans: (id: string) =>
    req<{ plans: HousePlan[] }>(`/arena/house/plans/${enc(id)}`),

  factorList: () => req<{ data: FactorInfo[] }>("/factor/list"),
  factorSubmit: (b: FactorJobIn) =>
    req<{ job_id: string }>("/factor/jobs", post(b)),
  factorJob: (id: string) => req<FactorJobState>(`/factor/jobs/${enc(id)}`),
};

export interface FactorInfo {
  id: string; name: string; sign: number; desc: string;
}

export interface FactorJobIn {
  factor?: string;
  composite?: { factor: string; sign: number }[] | null;
  universe?: string;
  universe_size?: number;
  symbols?: string[] | null;
  start_date?: string;
  end_date?: string;
  freq?: string;
  quantiles?: number;
}

export interface ICSummary {
  n: number; mean: number | null; std: number | null;
  icir: number | null; icir_ann: number | null; t: number | null;
  pos_ratio: number | null;
}

export interface FactorResult {
  params: Record<string, unknown>;
  universe: { count: number; dropped: string[] };
  dates_used: string[];
  dates_dropped_small: string[];
  ic_series: { date: string; ic: number | null; rank_ic: number | null; n: number }[];
  ic_summary: ICSummary;
  rank_ic_summary: ICSummary;
  quantile_nav: Record<string, { date: string; nav: number }[]>;
  quantile_annual: Record<string, number | null>;
  top_turnover: number | null;
  ic_decay: { lag: number; rank_ic_mean: number | null; n: number }[];
  notes: string[];
}

export interface FactorJobState {
  job_id: string;
  state: "queued" | "running" | "done" | "failed";
  progress: { loaded: number; total: number; stage: string };
  error: string | null;
  result: FactorResult | null;
}

function post(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
