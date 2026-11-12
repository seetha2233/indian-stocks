import { useState } from 'react'
import type { ReactNode } from 'react'

import type { Risk, Signal, Stock } from './api'
import { fmt } from './api'

export function Loadable<T>({
  state,
  children,
}: {
  state: { data: T | null; error: string | null; loading: boolean }
  children: (data: T) => ReactNode
}) {
  if (state.error) return <div className="error">Couldn't load: {state.error}</div>
  if (state.loading && !state.data) return <div className="loading">Loading…</div>
  if (!state.data) return null
  return <>{children(state.data)}</>
}

// Status chips always carry a text label; color is secondary
const SIGNAL_COLOR: Record<Signal, string> = {
  WATCH: 'var(--good)',
  NEUTRAL: 'var(--text-muted)',
  AVOID: 'var(--critical)',
  NEW: 'var(--accent)',
  LIMITED: 'var(--neutral-chip)',
}

export function SignalChip({ signal, large }: { signal: Signal; large?: boolean }) {
  return (
    <span className={`chip${large ? ' lg' : ''}`}>
      <span className="dot" style={{ background: SIGNAL_COLOR[signal] }} />
      {signal}
    </span>
  )
}

const RISK_COLOR: Record<Risk, string> = {
  Low: 'var(--good)',
  Medium: 'var(--warning)',
  High: 'var(--serious)',
}

export function RiskChip({ risk }: { risk: Risk | null }) {
  if (risk == null) return <span className="muted">—</span>
  return (
    <span className="chip">
      <span className="dot" style={{ background: RISK_COLOR[risk] }} />
      {risk} risk
    </span>
  )
}

export function Change({ value, digits = 2 }: { value: number | null | undefined; digits?: number }) {
  if (value == null) return <span className="muted">—</span>
  const cls = value > 0 ? 'up' : value < 0 ? 'down' : 'muted'
  const icon = value > 0 ? '▲' : value < 0 ? '▼' : ''
  return (
    <span className={cls}>
      {icon} {fmt.signedPct(value, digits)}
    </span>
  )
}

export function Meter({ label, value, hint }: { label: string; value: number | null; hint?: string }) {
  return (
    <div className="meter" title={hint}>
      <span className="secondary">{label}</span>
      <div className="track" role="meter" aria-valuenow={value ?? undefined} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className="fill" style={{ width: `${value ?? 0}%` }} />
      </div>
      <span className="v">{value == null ? <span className="muted">—</span> : Math.round(value)}</span>
    </div>
  )
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="panel stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub != null && <div className="sub">{sub}</div>}
    </div>
  )
}

export function Sentiment({ value }: { value: number | null }) {
  if (value == null) return <span className="muted small">unscored</span>
  const label = value >= 0.25 ? 'positive' : value <= -0.25 ? 'negative' : 'neutral'
  const cls = label === 'positive' ? 'up' : label === 'negative' ? 'down' : 'muted'
  const icon = label === 'positive' ? '▲' : label === 'negative' ? '▼' : '●'
  return (
    <span className={`small ${cls}`}>
      {icon} {label} ({value > 0 ? '+' : ''}
      {value.toFixed(2)})
    </span>
  )
}

// Type-to-search box over all covered stocks (a plain <select> with ~2,500
// options is unusable)
export function StockSearch({
  stocks,
  value,
  onPick,
  allowEmpty,
  placeholder = 'Search symbol or company',
}: {
  stocks: Stock[] | null
  value: string
  onPick: (symbol: string) => void
  allowEmpty?: boolean
  placeholder?: string
}) {
  const [text, setText] = useState('')
  const [focused, setFocused] = useState(false)

  const q = text.trim().toLowerCase()
  const matches =
    q.length === 0
      ? []
      : (stocks ?? [])
          .filter((s) => s.symbol.toLowerCase().startsWith(q) || s.name?.toLowerCase().includes(q))
          .sort((a, b) => Number(b.symbol.toLowerCase().startsWith(q)) - Number(a.symbol.toLowerCase().startsWith(q)))
          .slice(0, 12)

  const pick = (symbol: string) => {
    onPick(symbol)
    setText('')
    setFocused(false)
  }

  return (
    <div className="search">
      <input
        aria-label="Search stocks"
        placeholder={value ? `${value} · ${placeholder.toLowerCase()}` : placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setTimeout(() => setFocused(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && matches[0]) pick(matches[0].symbol)
          if (e.key === 'Escape') setText('')
        }}
        style={{ minWidth: 280 }}
      />
      {allowEmpty && value && (
        <button className="link small" onClick={() => pick('')} style={{ marginLeft: 8 }}>
          Clear
        </button>
      )}
      {focused && matches.length > 0 && (
        <ul className="search-results" role="listbox">
          {matches.map((s) => (
            <li key={s.symbol} role="option" onMouseDown={() => pick(s.symbol)}>
              <b>{s.symbol}</b> <span className="muted small">{s.name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
