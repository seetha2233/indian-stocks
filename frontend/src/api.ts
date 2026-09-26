// Typed client for the FastAPI backend (proxied at /api in dev)

export type Signal = 'WATCH' | 'NEUTRAL' | 'AVOID'
export type Risk = 'Low' | 'Medium' | 'High'

export interface Card {
  symbol: string
  name: string
  sector: string
  as_of: string
  price: number
  signal: Signal
  entry_zone: [number, number]
  target_1: number
  target_2: number
  stop_loss: number
  risk_reward: number
  upside_prob_20d: number
  risk: Risk
  annual_volatility: number
  turnover_cr: number | null
  nifty100: boolean
  scores: {
    technical: number | null
    fundamental: number | null
    news: number | null
    news_articles: number
    momentum: number | null
    composite: number | null
  }
  fundamentals: {
    pe: number | null
    pb: number | null
    roe: number | null
    valuation: number | null
    quality: number | null
    growth: number | null
    balance_sheet: number | null
  }
  why: string[]
  definitions: Record<string, string>
  disclaimer: string
}

// Screener rows (GET /signals?compact=true)
export type CompactCard = Pick<
  Card,
  'symbol' | 'name' | 'sector' | 'price' | 'signal' | 'upside_prob_20d' | 'risk' | 'annual_volatility' | 'risk_reward' | 'turnover_cr' | 'nifty100' | 'scores'
>

export interface NewsItem {
  id: string
  symbol: string
  title: string
  summary: string | null
  source: string
  url: string
  published: string
  relevant: boolean | null
  sentiment: number | null
  sentiment_reason: string | null
}

export interface Explanation {
  source: 'llm' | 'rules'
  summary: string | null
  bullets: string[]
  risks: string[]
  news_used?: string[]
  model?: string
  note?: string
  news: { id: string; title: string; source: string; published: string; sentiment: number | null; url: string }[]
}

export interface IndexQuote {
  name: string
  symbol: string
  price: number
  change: number
  change_percent: number
  as_of: string
}

export interface Mover {
  symbol: string
  name: string
  price: number
  change_percent: number
}

export interface Overview {
  as_of: string
  stocks: number
  movers_min_turnover_cr: number
  breadth: { advancing: number; declining: number; unchanged: number; above_sma_20_pct: number; above_sma_50_pct: number }
  market: { equal_weight_ret_1d: number; equal_weight_ret_20d: number; volatility_20d: number }
  gainers: Mover[]
  losers: Mover[]
  sectors: { sector: string; stocks: number; ret_1d: number; ret_20d: number; above_sma_20: number }[]
  signals: Partial<Record<Signal, number>>
  risk: Partial<Record<Risk, number>>
}

export interface Bar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  sma_20: number | null
  sma_50: number | null
}

export interface Source {
  type: 'card' | 'research' | 'news'
  title: string | null
  text: string
  symbol?: string | null
  source?: string | null
  url?: string | null
  published?: string | null
  sentiment?: number | null
}

export interface Answer {
  answer: string | null
  cited?: number[]
  note?: string
  sources: Source[]
}

export interface Position {
  id: number
  symbol: string
  status: 'open' | 'closed'
  signal: Signal | null
  opened_on: string
  entry_price: number
  quantity: number
  target: number | null
  stop_loss: number | null
  price: number
  as_of: string
  closed_on: string | null
  exit_reason: string | null
  cost_basis: number
  value: number
  pnl: number
  pnl_pct: number
  note: string | null
}

export interface PortfolioData {
  positions: Position[]
  summary: {
    open_positions: number
    open_value: number
    unrealized_pnl: number
    closed_positions: number
    realized_pnl: number
    win_rate: number | null
    costs_included: string
  }
}

export interface TrackerHorizon {
  status?: string
  signal_days?: number
  all_stocks_avg?: number
  by_signal?: Record<string, { count: number; avg_return: number; vs_all: number; win_rate: number }>
}

export interface Tracker {
  signal_days: number
  first_day: string | null
  horizons: Record<string, TrackerHorizon>
}

export interface BacktestRow {
  strategy: string
  gross_return: number
  total_return: number
  annual_return: number
  annual_vol: number
  sharpe: number
  max_drawdown: number
  trades: number | null
  win_rate: number | null
  avg_trade: number | null
  hit_limit: number | null
  avg_days: number | null
}

export interface Backtest {
  summary: BacktestRow[]
  curves: { dates: string[]; series: Record<string, (number | null)[]> }
}

export interface Health {
  status: string
  cache: string
  llm: string
  data: Record<string, string | null>
}

export interface Stock {
  symbol: string
  name: string
  sector: string
  industry: string
  market_cap: number
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      // not JSON
    }
    throw new Error(`${res.status}: ${detail}`)
  }

  return res.status === 204 ? (undefined as T) : res.json()
}

const qs = (params: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  health: () => request<Health>('/health'),
  indices: () => request<IndexQuote[]>('/market/indices'),
  overview: () => request<Overview>('/market/overview'),
  stocks: () => request<Stock[]>('/stocks'),
  history: (symbol: string, days = 250) => request<{ symbol: string; bars: Bar[] }>(`/stocks/${symbol}/history${qs({ days })}`),
  signals: (params: { signal?: string; risk?: string; sector?: string; sort?: string; limit?: number } = {}) =>
    request<Card[]>(`/signals${qs(params)}`),
  screener: () => request<CompactCard[]>('/signals?compact=true'),
  signal: (symbol: string) => request<Card>(`/signals/${symbol}`),
  explanation: (symbol: string) => request<Explanation>(`/signals/${symbol}/explanation`),
  news: (params: { symbol?: string; days?: number; limit?: number } = {}) => request<NewsItem[]>(`/news${qs(params)}`),
  ask: (question: string, symbol?: string) =>
    request<Answer>('/research/ask', { method: 'POST', body: JSON.stringify({ question, symbol: symbol || null }) }),
  portfolio: () => request<PortfolioData>('/portfolio'),
  addPosition: (body: { symbol: string; quantity: number; entry_price?: number; target?: number; stop_loss?: number; note?: string }) =>
    request<{ id: number }>('/portfolio', { method: 'POST', body: JSON.stringify(body) }),
  closePosition: (id: number) => request<{ closed: number }>(`/portfolio/${id}/close`, { method: 'POST' }),
  deletePosition: (id: number) => request<void>(`/portfolio/${id}`, { method: 'DELETE' }),
  tracker: () => request<Tracker>('/portfolio/signal-tracker'),
  backtest: () => request<Backtest>('/backtest'),
}

// Formatting

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 })
const num = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })

export const fmt = {
  inr: (x: number | null | undefined) => (x == null ? '—' : inr.format(x)),
  crore: (x: number | null | undefined) =>
    x == null ? '—' : x >= 1 ? `₹${num.format(Math.round(x * 10) / 10)} cr` : `₹${num.format(Math.round(x * 100))} lakh`,
  num: (x: number | null | undefined) => (x == null ? '—' : num.format(x)),
  pct: (x: number | null | undefined, digits = 1) => (x == null ? '—' : `${x.toFixed(digits)}%`),
  signedPct: (x: number | null | undefined, digits = 2) => (x == null ? '—' : `${x > 0 ? '+' : ''}${x.toFixed(digits)}%`),
  // fraction (0.12) -> "12%"
  frac: (x: number | null | undefined, digits = 0) => (x == null ? '—' : `${(x * 100).toFixed(digits)}%`),
  signedFrac: (x: number | null | undefined, digits = 1) =>
    x == null ? '—' : `${x > 0 ? '+' : ''}${(x * 100).toFixed(digits)}%`,
  score: (x: number | null | undefined) => (x == null ? '—' : `${Math.round(x)}`),
}
