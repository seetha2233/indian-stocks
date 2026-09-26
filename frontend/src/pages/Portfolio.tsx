import { useState } from 'react'
import { Link } from 'react-router-dom'

import type { Backtest, Tracker } from '../api'
import { api, fmt } from '../api'
import { EquityChart } from '../charts'
import { Change, Loadable, SignalChip, Stat } from '../components'
import { useApi } from '../hooks'

// The three curves that tell the story; every strategy is in the table
const HEADLINE = ['Model top 10, sell at +5%', 'All liquid stocks, sell at +5%', 'Buy & hold (all liquid stocks)']

function PaperPortfolio() {
  const state = useApi(api.portfolio)
  const [symbol, setSymbol] = useState('')
  const [qty, setQty] = useState(10)
  const [error, setError] = useState<string | null>(null)

  const add = async () => {
    setError(null)
    try {
      await api.addPosition({ symbol: symbol.trim().toUpperCase(), quantity: qty })
      setSymbol('')
      state.reload()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      state.reload()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Paper portfolio</h2>
        <span className="small muted">positions close themselves at target or stop · costs included</span>
      </div>

      <form
        className="controls"
        onSubmit={(e) => {
          e.preventDefault()
          add()
        }}
      >
        <div className="field">
          <label htmlFor="psym">Symbol</label>
          <input id="psym" placeholder="e.g. TCS" value={symbol} onChange={(e) => setSymbol(e.target.value)} style={{ width: 140 }} />
        </div>
        <div className="field">
          <label htmlFor="pqty">Quantity</label>
          <input id="pqty" type="number" min={1} value={qty} onChange={(e) => setQty(Math.max(1, Number(e.target.value)))} style={{ width: 100 }} />
        </div>
        <button className="primary" type="submit" disabled={!symbol.trim()}>
          Open at latest close
        </button>
        {error && <span className="error small" style={{ padding: 0 }}>{error}</span>}
      </form>

      <Loadable state={state}>
        {(p) => (
          <>
            <div className="grid cols-4" style={{ marginBottom: 12 }}>
              <Stat label="Open positions" value={p.summary.open_positions} sub={<span className="muted">worth {fmt.inr(p.summary.open_value)}</span>} />
              <Stat label="Unrealised P&L" value={fmt.inr(p.summary.unrealized_pnl)} />
              <Stat label="Realised P&L" value={fmt.inr(p.summary.realized_pnl)} sub={<span className="muted">{p.summary.closed_positions} closed</span>} />
              <Stat label="Win rate (closed)" value={fmt.pct(p.summary.win_rate)} sub={<span className="muted">{p.summary.costs_included}</span>} />
            </div>
            {p.positions.length === 0 ? (
              <div className="muted">
                No positions yet. Open one here or from a stock's <Link to="/stock/RELIANCE">Deep Dive</Link>.
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Stock</th>
                      <th>Status</th>
                      <th>Signal at entry</th>
                      <th>Opened</th>
                      <th className="num">Qty</th>
                      <th className="num">Entry</th>
                      <th className="num">Target</th>
                      <th className="num">Stop</th>
                      <th className="num">Price</th>
                      <th className="num">P&L</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {p.positions.map((r) => (
                      <tr key={r.id}>
                        <td>
                          <Link to={`/stock/${r.symbol}`}>
                            <b>{r.symbol}</b>
                          </Link>
                        </td>
                        <td>
                          {r.status === 'open' ? 'Open' : `Closed (${r.exit_reason}) ${r.closed_on}`}
                        </td>
                        <td>{r.signal ? <SignalChip signal={r.signal} /> : '—'}</td>
                        <td>{r.opened_on}</td>
                        <td className="num">{r.quantity}</td>
                        <td className="num">{fmt.inr(r.entry_price)}</td>
                        <td className="num">{fmt.inr(r.target)}</td>
                        <td className="num">{fmt.inr(r.stop_loss)}</td>
                        <td className="num">{fmt.inr(r.price)}</td>
                        <td className="num">
                          {fmt.inr(r.pnl)} <Change value={r.pnl_pct} />
                        </td>
                        <td>
                          {r.status === 'open' ? (
                            <button className="small" onClick={() => act(() => api.closePosition(r.id))}>
                              Close
                            </button>
                          ) : (
                            <button className="small" onClick={() => act(() => api.deletePosition(r.id))}>
                              Remove
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Loadable>
    </div>
  )
}

function SignalTracker({ t }: { t: Tracker }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Signal tracker (forward test)</h2>
        <span className="small muted">
          {t.signal_days} signal day{t.signal_days === 1 ? '' : 's'} recorded since {t.first_day ?? '—'}
        </span>
      </div>
      <p className="small secondary" style={{ marginTop: 0 }}>
        How stocks did after each day's signals, measured from that day's close. This is the only honest test of the news
        and fundamental scores, which have no history to backtest. It fills in as the daily refresh runs.
      </p>
      {Object.entries(t.horizons).map(([h, v]) => (
        <div key={h} style={{ marginTop: 10 }}>
          <h3>Next {h.replace('d', ' trading days')}</h3>
          {v.status ? (
            <div className="muted small">{v.status}</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Signal</th>
                  <th className="num">Stock-days</th>
                  <th className="num">Avg return</th>
                  <th className="num">vs all stocks</th>
                  <th className="num">Win rate</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(v.by_signal ?? {}).map(([s, r]) => (
                  <tr key={s}>
                    <td>{s}</td>
                    <td className="num">{r.count}</td>
                    <td className="num">
                      <Change value={r.avg_return} />
                    </td>
                    <td className="num">
                      <Change value={r.vs_all} />
                    </td>
                    <td className="num">{fmt.pct(r.win_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </div>
  )
}

// Written from the numbers, so it can't go stale when the backtest reruns
function Verdict({ b }: { b: Backtest }) {
  const models = b.summary.filter((r) => r.strategy.startsWith('Model'))
  const hold = b.summary.find((r) => r.strategy.startsWith('Buy & hold'))
  if (!models.length || !hold) return null

  const best = models.reduce((a, r) => (r.total_return > a.total_return ? r : a))
  const days = b.curves.dates.length
  const beat = best.total_return > hold.total_return

  return (
    <div className="notice" style={{ marginTop: 12 }}>
      What this shows: the best model strategy ({best.strategy}) returned {fmt.signedFrac(best.total_return)} after costs
      versus {fmt.signedFrac(hold.total_return)} for buy-and-hold, so it {beat ? 'beat' : 'did not beat'} holding.
      {days < 120 && (
        <>
          {' '}
          This covers only {days} trading days, which is too short to be statistically reliable: treat it as a hypothesis
          and watch the signal tracker above to see whether it holds up.
        </>
      )}{' '}
      The models estimate how far a stock may move (range, volatility) far better than which way.
    </div>
  )
}

function BacktestPanel({ b }: { b: Backtest }) {
  const series = HEADLINE.filter((n) => b.curves.series[n]).map((n) => ({ name: n, values: b.curves.series[n] }))
  const start = b.curves.dates[0]
  const end = b.curves.dates[b.curves.dates.length - 1]

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Walk-forward backtest</h2>
        <span className="small muted">
          {start} → {end} ({b.curves.dates.length} trading days) · retrained every 10 days · buy at next open · 0.3%
          round-trip costs · stocks trading ≥ ₹5 cr/day
        </span>
      </div>
      <EquityChart dates={b.curves.dates} series={series} />
      <div className="table-wrap" style={{ marginTop: 12 }}>
        <table>
          <thead>
            <tr>
              <th>Strategy</th>
              <th className="num">Before costs</th>
              <th className="num">After costs</th>
              <th className="num">Sharpe</th>
              <th className="num">Max drawdown</th>
              <th className="num">Trades</th>
              <th className="num">Win rate</th>
              <th className="num">Reached limit</th>
            </tr>
          </thead>
          <tbody>
            {b.summary.map((r) => (
              <tr key={r.strategy}>
                <td>{r.strategy}</td>
                <td className="num">{fmt.signedFrac(r.gross_return)}</td>
                <td className="num">
                  <b>{fmt.signedFrac(r.total_return)}</b>
                </td>
                <td className="num">{fmt.num(r.sharpe)}</td>
                <td className="num">{fmt.frac(r.max_drawdown, 1)}</td>
                <td className="num">{r.trades ?? '—'}</td>
                <td className="num">{fmt.frac(r.win_rate, 1)}</td>
                <td className="num">{fmt.frac(r.hit_limit, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Verdict b={b} />
    </div>
  )
}

export default function Portfolio() {
  const backtest = useApi(api.backtest)
  const tracker = useApi(api.tracker)

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Backtesting / Paper Portfolio</h1>
          <p>Test ideas without real money, and see how the models and signals have actually performed.</p>
        </div>
      </div>

      <PaperPortfolio />

      <Loadable state={tracker}>{(t) => <SignalTracker t={t} />}</Loadable>

      <Loadable state={backtest}>{(b) => <BacktestPanel b={b} />}</Loadable>
    </div>
  )
}
