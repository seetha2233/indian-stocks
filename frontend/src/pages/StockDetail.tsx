import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import type { Card } from '../api'
import { api, fmt } from '../api'
import { PriceChart } from '../charts'
import { Loadable, Meter, RiskChip, Sentiment, SignalChip, StockSearch } from '../components'
import { useApi } from '../hooks'

function StockPicker({ current }: { current: string }) {
  const navigate = useNavigate()
  const stocks = useApi(api.stocks)
  return <StockSearch stocks={stocks.data} value={current} onPick={(sym) => sym && navigate(`/stock/${sym}`)} />
}

function CardPanel({ c }: { c: Card }) {
  const d = c.definitions
  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <h2 style={{ fontSize: 20 }}>{c.symbol}</h2>
          <div className="small muted">
            {c.name}
            {c.sector ? ` · ${c.sector}` : ''}
            {c.nifty100 ? ' · NIFTY 100' : ''}
          </div>
        </div>
        <SignalChip signal={c.signal} large />
      </div>

      <dl className="kv">
        <dt>Current price</dt>
        <dd>{fmt.inr(c.price)}</dd>
        <dt>AI signal</dt>
        <dd>{c.signal}</dd>
      </dl>

      <hr style={{ border: 0, borderTop: '1px solid var(--border)', margin: '12px 0' }} />

      <dl className="kv">
        <dt title={d.entry_zone}>Entry zone</dt>
        <dd>
          {fmt.inr(c.entry_zone[0])} – {fmt.inr(c.entry_zone[1])}
        </dd>
        <dt title={d.target_1}>Target 1 (1-week)</dt>
        <dd>
          {fmt.inr(c.target_1)} <span className="muted small">({fmt.signedFrac(c.target_1 / c.price - 1)})</span>
        </dd>
        <dt title={d.target_2}>Target 2 (20-day)</dt>
        <dd>
          {fmt.inr(c.target_2)} <span className="muted small">({fmt.signedFrac(c.target_2 / c.price - 1)})</span>
        </dd>
        <dt title={d.stop_loss}>Stop loss</dt>
        <dd>
          {fmt.inr(c.stop_loss)} <span className="muted small">({fmt.signedFrac(c.stop_loss / c.price - 1)})</span>
        </dd>
        <dt>Risk / reward</dt>
        <dd>{fmt.num(c.risk_reward)}</dd>
      </dl>

      <hr style={{ border: 0, borderTop: '1px solid var(--border)', margin: '12px 0' }} />

      <dl className="kv">
        <dt title={d.upside_prob_20d}>20D upside prob.</dt>
        <dd>{fmt.frac(c.upside_prob_20d)}</dd>
        <dt title={d.risk}>Risk</dt>
        <dd>
          <RiskChip risk={c.risk} />
        </dd>
        <dt>Predicted volatility</dt>
        <dd>{fmt.frac(c.annual_volatility)} a year</dd>
        <dt title={d.liquidity}>Traded per day</dt>
        <dd>
          {fmt.crore(c.turnover_cr)}
          {(c.turnover_cr ?? 0) < 5 && <span className="muted small"> (thin)</span>}
        </dd>
      </dl>

      <hr style={{ border: 0, borderTop: '1px solid var(--border)', margin: '12px 0' }} />

      <Meter label="Technical" value={c.scores.technical} hint={d.scores} />
      <Meter label="Fundamental" value={c.scores.fundamental} hint="Sector-relative valuation, quality, growth, leverage" />
      <Meter
        label="News"
        value={c.scores.news}
        hint={d.news_score ?? 'LLM sentiment of recent news'}
      />
      <Meter label="Momentum" value={c.scores.momentum} hint={d.scores} />
      <div className="small muted" style={{ marginTop: 6 }}>
        {c.scores.news == null
          ? 'News score needs LLM sentiment and at least 2 relevant articles.'
          : `News from ${c.scores.news_articles} relevant articles.`}{' '}
        As of {c.as_of}.
      </div>
    </div>
  )
}

function Why({ symbol }: { symbol: string }) {
  const state = useApi(() => api.explanation(symbol), [symbol])
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Why?</h2>
        {state.data && (
          <span className="small muted">
            {state.data.source === 'llm' ? `AI explanation (${state.data.model})` : 'Rule-based reasons'}
          </span>
        )}
      </div>
      <Loadable state={state}>
        {(e) => (
          <>
            {e.summary && <p style={{ marginTop: 0 }}>{e.summary}</p>}
            <ul className="bullets">
              {e.bullets.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
            {e.risks.length > 0 && (
              <>
                <h3 style={{ marginTop: 12 }}>Risks and caveats</h3>
                <ul className="bullets">
                  {e.risks.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </>
            )}
            {e.note && <p className="small muted">{e.note}</p>}
          </>
        )}
      </Loadable>
    </div>
  )
}

function AddToPortfolio({ c }: { c: Card }) {
  const [qty, setQty] = useState(10)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const add = async () => {
    setBusy(true)
    setStatus(null)
    try {
      await api.addPosition({ symbol: c.symbol, quantity: qty })
      setStatus(`Added ${qty} × ${c.symbol} at ${fmt.inr(c.price)} with target ${fmt.inr(c.target_2)} and stop ${fmt.inr(c.stop_loss)}.`)
    } catch (e) {
      setStatus(`Couldn't add: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <h2>Paper trade</h2>
      <p className="small secondary" style={{ marginTop: 0 }}>
        Opens at the latest close with Target 2 and the stop loss. It closes itself when either is hit.
      </p>
      <div className="row">
        <div className="field">
          <label htmlFor="qty">Quantity</label>
          <input id="qty" type="number" min={1} value={qty} onChange={(e) => setQty(Math.max(1, Number(e.target.value)))} style={{ width: 100 }} />
        </div>
        <button className="primary" onClick={add} disabled={busy} style={{ alignSelf: 'end' }}>
          Add to paper portfolio
        </button>
      </div>
      {status && (
        <p className="small" style={{ marginBottom: 0 }}>
          {status} <Link to="/portfolio">View portfolio →</Link>
        </p>
      )}
    </div>
  )
}

export default function StockDetail() {
  const { symbol = 'RELIANCE' } = useParams()
  const sym = symbol.toUpperCase()

  const card = useApi(() => api.signal(sym), [sym])
  const history = useApi(() => api.history(sym, 250), [sym])
  const news = useApi(() => api.news({ symbol: sym, days: 5, limit: 15 }), [sym])

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Stock Deep Dive</h1>
          <p>The full stock card, price levels, fundamentals and news.</p>
        </div>
        <div className="row">
          <StockPicker current={sym} />
          <Link to={`/research?symbol=${sym}`}>Ask about {sym} →</Link>
        </div>
      </div>

      <Loadable state={card}>
        {(c) => (
          <>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 360px), 1fr))' }}>
              <CardPanel c={c} />
              <div className="stack">
                <Why symbol={sym} />
                <AddToPortfolio c={c} />
              </div>
            </div>

            <div className="panel">
              <div className="panel-head">
                <h2>Price, last 6 months</h2>
                <span className="small muted">as traded (not adjusted); dashed lines are this card's levels</span>
              </div>
              <Loadable state={history}>{(h) => <PriceChart bars={h.bars} card={c} />}</Loadable>
            </div>

            <div className="grid cols-2">
              <div className="panel">
                <h2>Fundamentals</h2>
                <dl className="kv">
                  <dt>P/E</dt>
                  <dd>{fmt.num(c.fundamentals.pe)}</dd>
                  <dt>P/B</dt>
                  <dd>{fmt.num(c.fundamentals.pb)}</dd>
                  <dt>ROE</dt>
                  <dd>{fmt.frac(c.fundamentals.roe, 1)}</dd>
                </dl>
                <div style={{ marginTop: 12 }}>
                  <Meter label="Valuation" value={c.fundamentals.valuation} />
                  <Meter label="Quality" value={c.fundamentals.quality} />
                  <Meter label="Growth" value={c.fundamentals.growth} />
                  <Meter label="Balance sheet" value={c.fundamentals.balance_sheet} />
                </div>
                <p className="small muted">
                  Percentiles vs sector peers (or all covered stocks where a sector has fewer than 5). Source: Yahoo
                  Finance snapshot; coverage is thinner for small companies.
                </p>
              </div>

              <div className="panel">
                <h2>Recent news (5 days)</h2>
                <Loadable state={news}>
                  {(items) =>
                    items.length === 0 ? (
                      <div className="muted">No recent articles.</div>
                    ) : (
                      <ul className="clean" style={{ maxHeight: 420, overflowY: 'auto' }}>
                        {items.map((n) => (
                          <li key={n.id} className="news-item">
                            <a href={n.url} target="_blank" rel="noreferrer">
                              {n.title}
                            </a>
                            <div className="meta">
                              <span>{n.source}</span>
                              <span>{n.published}</span>
                              {n.relevant === false ? (
                                <span className="muted small">not about this company</span>
                              ) : (
                                <Sentiment value={n.sentiment} />
                              )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    )
                  }
                </Loadable>
              </div>
            </div>

            <p className="disclaimer">{c.disclaimer}</p>
          </>
        )}
      </Loadable>
    </div>
  )
}
