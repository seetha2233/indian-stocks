import { Link, useNavigate } from 'react-router-dom'

import type { Mover } from '../api'
import { api, fmt } from '../api'
import { DivergingBars } from '../charts'
import { Change, Loadable, RiskChip, SignalChip, Stat } from '../components'
import { useApi } from '../hooks'

function Movers({ title, rows }: { title: string; rows: Mover[] }) {
  const navigate = useNavigate()
  return (
    <div className="panel">
      <h2>{title}</h2>
      <table>
        <tbody>
          {rows.map((m) => (
            <tr key={m.symbol} className="clickable" onClick={() => navigate(`/stock/${m.symbol}`)}>
              <td>
                <b>{m.symbol}</b>
                <div className="small muted">{m.name}</div>
              </td>
              <td className="num">{fmt.inr(m.price)}</td>
              <td className="num">
                <Change value={m.change_percent} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Dashboard() {
  const indices = useApi(api.indices)
  const overview = useApi(api.overview)
  const watch = useApi(() => api.signals({ signal: 'WATCH', sort: 'composite', limit: 8 }))
  const news = useApi(() => api.news({ symbol: 'MARKET', days: 2, limit: 6 }))

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Market Dashboard</h1>
          <p>Breadth, sectors and today's AI signals across all covered NSE stocks.</p>
        </div>
      </div>

      <Loadable state={indices}>
        {(rows) => (
          <div className="grid cols-4">
            {rows.map((ix) => (
              <Stat
                key={ix.symbol}
                label={ix.name}
                value={fmt.num(ix.price)}
                sub={
                  <>
                    <Change value={ix.change_percent} />{' '}
                    <span className="muted">
                      ({ix.change > 0 ? '+' : ''}
                      {fmt.num(ix.change)})
                    </span>
                  </>
                }
              />
            ))}
          </div>
        )}
      </Loadable>

      <Loadable state={overview}>
        {(o) => (
          <>
            <div className="grid cols-4">
              <Stat
                label="Advancing / declining"
                value={`${o.breadth.advancing} / ${o.breadth.declining}`}
                sub={<span className="muted">of {fmt.num(o.stocks)} stocks, on {o.as_of}</span>}
              />
              <Stat
                label="Above 20-day average"
                value={fmt.pct(o.breadth.above_sma_20_pct, 0)}
                sub={<span className="muted">{fmt.pct(o.breadth.above_sma_50_pct, 0)} above 50-day</span>}
              />
              <Stat
                label="All stocks equal-weight, 20 days"
                value={<Change value={o.market.equal_weight_ret_20d} />}
                sub={
                  <span className="muted">
                    today <Change value={o.market.equal_weight_ret_1d} />
                  </span>
                }
              />
              <Stat
                label="AI signals today"
                value={`${o.signals.WATCH ?? 0} watch`}
                sub={
                  <span className="muted">
                    {o.signals.NEUTRAL ?? 0} neutral · {o.signals.AVOID ?? 0} avoid
                  </span>
                }
              />
            </div>

            <div className="grid cols-2">
              <div className="panel">
                <div className="panel-head">
                  <h2>Sector performance, last 20 days</h2>
                  <span className="small muted">equal-weight average of covered stocks</span>
                </div>
                <DivergingBars
                  valueLabel="20-day return"
                  data={o.sectors.map((s) => ({
                    label: `${s.sector} (${s.stocks})`,
                    value: s.ret_20d,
                    extra: `${fmt.pct(s.above_sma_20, 0)} above 20-day avg`,
                  }))}
                />
              </div>
              <div className="stack">
                <Movers title={`Top gainers today (≥ ₹${o.movers_min_turnover_cr} cr traded/day)`} rows={o.gainers} />
                <Movers title={`Top losers today (≥ ₹${o.movers_min_turnover_cr} cr traded/day)`} rows={o.losers} />
              </div>
            </div>
          </>
        )}
      </Loadable>

      <div className="grid cols-2">
        <div className="panel">
          <div className="panel-head">
            <h2>Top WATCH signals</h2>
            <Link to="/screener" className="small">
              Open screener →
            </Link>
          </div>
          <Loadable state={watch}>
            {(cards) =>
              cards.length === 0 ? (
                <div className="muted">No WATCH signals today.</div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Stock</th>
                        <th className="num">Price</th>
                        <th>Signal</th>
                        <th className="num">Score</th>
                        <th className="num">20D upside</th>
                        <th>Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cards.map((c) => (
                        <tr key={c.symbol}>
                          <td>
                            <Link to={`/stock/${c.symbol}`}>
                              <b>{c.symbol}</b>
                            </Link>
                          </td>
                          <td className="num">{fmt.inr(c.price)}</td>
                          <td>
                            <SignalChip signal={c.signal} />
                          </td>
                          <td className="num">{fmt.score(c.scores.composite)}</td>
                          <td className="num">{fmt.frac(c.upside_prob_20d)}</td>
                          <td>
                            <RiskChip risk={c.risk} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </Loadable>
          <p className="disclaimer">
            Signals are a transparent rule on scores and are not validated predictions. See Backtest.
          </p>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>Market news</h2>
            <Link to="/research" className="small">
              All news →
            </Link>
          </div>
          <Loadable state={news}>
            {(items) => (
              <ul className="clean">
                {items.map((n) => (
                  <li key={n.id} className="news-item">
                    <a href={n.url} target="_blank" rel="noreferrer">
                      {n.title}
                    </a>
                    <div className="meta">
                      <span>{n.source}</span>
                      <span>{n.published}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Loadable>
        </div>
      </div>
    </div>
  )
}
