import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import type { CompactCard as Card } from '../api'
import { api, fmt } from '../api'
import { Loadable, RiskChip, SignalChip } from '../components'
import { useApi } from '../hooks'

type SortKey = 'symbol' | 'price' | 'composite' | 'technical' | 'momentum' | 'fundamental' | 'news' | 'upside' | 'rr' | 'vol' | 'liq'

const VALUE: Record<SortKey, (c: Card) => number | string | null> = {
  symbol: (c) => c.symbol,
  price: (c) => c.price,
  composite: (c) => c.scores.composite,
  technical: (c) => c.scores.technical,
  momentum: (c) => c.scores.momentum,
  fundamental: (c) => c.scores.fundamental,
  news: (c) => c.scores.news,
  upside: (c) => c.upside_prob_20d,
  rr: (c) => c.risk_reward,
  vol: (c) => c.annual_volatility,
  liq: (c) => c.turnover_cr,
}

const COLUMNS: { key: SortKey; label: string; num?: boolean; title?: string }[] = [
  { key: 'symbol', label: 'Stock' },
  { key: 'price', label: 'Price', num: true },
  { key: 'composite', label: 'Composite', num: true, title: 'Average of the available scores' },
  { key: 'technical', label: 'Technical', num: true },
  { key: 'momentum', label: 'Momentum', num: true },
  { key: 'fundamental', label: 'Fundamental', num: true },
  { key: 'news', label: 'News', num: true, title: 'Empty until LLM sentiment is enabled' },
  { key: 'upside', label: '20D upside', num: true, title: 'Chance of touching +5% within 20 trading days' },
  { key: 'rr', label: 'Risk/reward', num: true, title: '(Target 2 − price) / (price − stop)' },
  { key: 'vol', label: 'Pred. volatility', num: true, title: 'Risk model: annualised' },
  { key: 'liq', label: 'Traded/day', num: true, title: 'Median daily traded value, last 20 days' },
]

const PAGE = 300

// WATCH needs this much daily trading; same bar as the backtest
const LIQUID_CR = 5

export default function Screener() {
  const navigate = useNavigate()
  const state = useApi(api.screener)

  const [signal, setSignal] = useState('')
  const [risk, setRisk] = useState('')
  const [sector, setSector] = useState('')
  const [query, setQuery] = useState('')
  const [universe, setUniverse] = useState('')
  const [liquidOnly, setLiquidOnly] = useState(true)
  const [page, setPage] = useState({ key: '', n: PAGE })
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'composite', desc: true })

  // Back to the first page whenever the filters or sort change
  const filterKey = JSON.stringify([signal, risk, sector, universe, liquidOnly, query, sort])
  const shown = page.key === filterKey ? page.n : PAGE

  const sectors = useMemo(
    () => [...new Set((state.data ?? []).map((c) => c.sector).filter(Boolean))].sort(),
    [state.data],
  )

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = (state.data ?? []).filter(
      (c) =>
        (!signal || c.signal === signal) &&
        (!risk || c.risk === risk) &&
        (!sector || c.sector === sector) &&
        (!universe || c.nifty100) &&
        (!liquidOnly || (c.turnover_cr ?? 0) >= LIQUID_CR) &&
        (!q || c.symbol.toLowerCase().includes(q) || c.name?.toLowerCase().includes(q)),
    )
    const get = VALUE[sort.key]
    return list.sort((a, b) => {
      const x = get(a)
      const y = get(b)
      if (x == null) return 1
      if (y == null) return -1
      const cmp = typeof x === 'string' ? x.localeCompare(String(y)) : x - Number(y)
      return sort.desc ? -cmp : cmp
    })
  }, [state.data, signal, risk, sector, universe, liquidOnly, query, sort])

  const header = (key: SortKey) =>
    setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== 'symbol' }))

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>AI Stock Screener</h1>
          <p>Stock cards for every covered NSE stock. Scores are percentiles vs all of them today (100 = best).</p>
        </div>
      </div>

      <div className="panel">
        <div className="controls">
          <div className="field">
            <label htmlFor="q">Search</label>
            <input id="q" placeholder="Symbol or name" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="uni">Universe</label>
            <select id="uni" value={universe} onChange={(e) => setUniverse(e.target.value)}>
              <option value="">All NSE</option>
              <option value="nifty100">NIFTY 100</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="sig">Signal</label>
            <select id="sig" value={signal} onChange={(e) => setSignal(e.target.value)}>
              <option value="">All</option>
              <option>WATCH</option>
              <option>NEUTRAL</option>
              <option>AVOID</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="risk">Risk</label>
            <select id="risk" value={risk} onChange={(e) => setRisk(e.target.value)}>
              <option value="">All</option>
              <option>Low</option>
              <option>Medium</option>
              <option>High</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="sector">Sector</label>
            <select id="sector" value={sector} onChange={(e) => setSector(e.target.value)}>
              <option value="">All</option>
              {sectors.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <label className="row small secondary" style={{ gap: 6, alignSelf: 'center', marginTop: 16 }}>
            <input type="checkbox" checked={liquidOnly} onChange={(e) => setLiquidOnly(e.target.checked)} />
            Liquid only (≥ ₹{LIQUID_CR} cr traded/day)
          </label>
          <span className="small muted" style={{ marginLeft: 'auto' }}>
            {rows.length} stocks
          </span>
        </div>

        <Loadable state={state}>
          {() => (
            <div className="table-wrap" style={{ maxHeight: '70vh' }}>
              <table>
                <thead>
                  <tr>
                    {COLUMNS.slice(0, 2).map((c) => (
                      <th key={c.key} className={`sortable${c.num ? ' num' : ''}`} onClick={() => header(c.key)}>
                        {c.label}
                        {sort.key === c.key ? (sort.desc ? ' ↓' : ' ↑') : ''}
                      </th>
                    ))}
                    <th>Signal</th>
                    {COLUMNS.slice(2).map((c) => (
                      <th
                        key={c.key}
                        title={c.title}
                        className={`sortable${c.num ? ' num' : ''}`}
                        onClick={() => header(c.key)}
                      >
                        {c.label}
                        {sort.key === c.key ? (sort.desc ? ' ↓' : ' ↑') : ''}
                      </th>
                    ))}
                    <th>Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, shown).map((c) => (
                    <tr key={c.symbol} className="clickable" onClick={() => navigate(`/stock/${c.symbol}`)}>
                      <td>
                        <b>{c.symbol}</b>
                        {c.nifty100 && <span className="small muted"> · N100</span>}
                        <div className="small muted">{c.sector ?? '—'}</div>
                      </td>
                      <td className="num">{fmt.inr(c.price)}</td>
                      <td>
                        <SignalChip signal={c.signal} />
                      </td>
                      <td className="num">
                        <b>{fmt.score(c.scores.composite)}</b>
                      </td>
                      <td className="num">{fmt.score(c.scores.technical)}</td>
                      <td className="num">{fmt.score(c.scores.momentum)}</td>
                      <td className="num">{fmt.score(c.scores.fundamental)}</td>
                      <td className="num">{fmt.score(c.scores.news)}</td>
                      <td className="num">{fmt.frac(c.upside_prob_20d)}</td>
                      <td className="num">{fmt.num(c.risk_reward)}</td>
                      <td className="num">{fmt.frac(c.annual_volatility)}</td>
                      <td className="num">{fmt.crore(c.turnover_cr)}</td>
                      <td>
                        <RiskChip risk={c.risk} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length > shown && (
                <div className="row" style={{ justifyContent: 'center', padding: 12 }}>
                  <button onClick={() => setPage({ key: filterKey, n: shown + PAGE })}>
                    Show {Math.min(PAGE, rows.length - shown)} more of {rows.length - shown}
                  </button>
                </div>
              )}
            </div>
          )}
        </Loadable>
        <p className="disclaimer">
          Research output, not investment advice. The WATCH / NEUTRAL / AVOID rule has not been validated as a predictor;
          the models estimate price range and volatility, not direction.
        </p>
      </div>
    </div>
  )
}
