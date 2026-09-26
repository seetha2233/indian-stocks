import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import type { Answer } from '../api'
import { api } from '../api'
import { Loadable, Sentiment, StockSearch } from '../components'
import { useApi } from '../hooks'

const EXAMPLES = [
  'Why is this stock falling?',
  'What are the main risks right now?',
  'How reliable are the targets?',
  'Summarise the latest news',
]

function AnswerView({ a }: { a: Answer }) {
  return (
    <div>
      {a.answer ? (
        <div className="chat-answer">{a.answer}</div>
      ) : (
        <div className="notice">{a.note}</div>
      )}
      <h3 style={{ marginTop: 16 }}>Sources</h3>
      {a.sources.map((s, i) => (
        <div
          key={i}
          className="source"
          style={a.cited?.includes(i + 1) ? { borderColor: 'var(--accent)' } : undefined}
        >
          <span className="n">[{i + 1}]</span>
          <span className="small muted">{s.type === 'news' ? s.source : s.type === 'card' ? 'Stock card' : 'Platform research'}</span>{' '}
          {s.url ? (
            <a href={s.url} target="_blank" rel="noreferrer">
              {s.title}
            </a>
          ) : (
            <b>{s.title}</b>
          )}
          {s.published && <span className="small muted"> · {s.published}</span>}
          {s.type !== 'news' && (
            <details>
              <summary className="small muted">Show text</summary>
              <div className="small secondary" style={{ whiteSpace: 'pre-wrap', marginTop: 6 }}>
                {s.text}
              </div>
            </details>
          )}
        </div>
      ))}
    </div>
  )
}

export default function Research() {
  const [params, setParams] = useSearchParams()
  const symbol = params.get('symbol') ?? ''

  const stocks = useApi(api.stocks)
  const news = useApi(() => api.news({ symbol: symbol || undefined, days: 5, limit: 60 }), [symbol])

  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const ask = async (q: string) => {
    if (q.trim().length < 3) return
    setBusy(true)
    setError(null)
    try {
      setAnswer(await api.ask(q.trim(), symbol || undefined))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>News + AI Research</h1>
          <p>Ask questions answered from our model results and recent news, with sources.</p>
        </div>
        <div className="field">
          <label>Stock (optional)</label>
          <StockSearch
            stocks={stocks.data}
            value={symbol}
            allowEmpty
            placeholder="All stocks + market"
            onPick={(sym) => {
              setAnswer(null)
              setParams(sym ? { symbol: sym } : {})
            }}
          />
        </div>
      </div>

      <div className="grid cols-2">
        <div className="panel">
          <h2>Ask {symbol || 'the research assistant'}</h2>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              ask(question)
            }}
          >
            <textarea
              rows={3}
              style={{ width: '100%', resize: 'vertical' }}
              placeholder={symbol ? `e.g. What's driving ${symbol} this week?` : 'e.g. Which small-cap pharma stocks have positive news?'}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={500}
            />
            <div className="row" style={{ marginTop: 8 }}>
              <button className="primary" type="submit" disabled={busy || question.trim().length < 3}>
                {busy ? 'Thinking…' : 'Ask'}
              </button>
              {EXAMPLES.map((q) => (
                <button
                  key={q}
                  type="button"
                  className="small"
                  onClick={() => {
                    setQuestion(q)
                    ask(q)
                  }}
                  disabled={busy}
                >
                  {q}
                </button>
              ))}
            </div>
          </form>
          <div style={{ marginTop: 16 }}>
            {error && <div className="error">{error}</div>}
            {answer && <AnswerView a={answer} />}
          </div>
          <p className="disclaimer">
            Answers use only retrieved sources (stock cards, model and backtest results, news) and are not investment
            advice.
          </p>
        </div>

        <div className="panel">
          <h2>{symbol ? `${symbol} news` : 'Latest news'} (5 days)</h2>
          <Loadable state={news}>
            {(items) =>
              items.length === 0 ? (
                <div className="muted">No articles.</div>
              ) : (
                <ul className="clean" style={{ maxHeight: '75vh', overflowY: 'auto' }}>
                  {items.map((n) => (
                    <li key={`${n.id}-${n.symbol}`} className="news-item">
                      <a href={n.url} target="_blank" rel="noreferrer">
                        {n.title}
                      </a>
                      <div className="meta">
                        {!symbol && n.symbol !== 'MARKET' && <b>{n.symbol}</b>}
                        <span>{n.source}</span>
                        <span>{n.published}</span>
                        {n.symbol !== 'MARKET' &&
                          (n.relevant === false ? (
                            <span className="muted small">not about this company</span>
                          ) : (
                            <Sentiment value={n.sentiment} />
                          ))}
                      </div>
                      {n.sentiment_reason && n.relevant && <div className="small secondary">{n.sentiment_reason}</div>}
                    </li>
                  ))}
                </ul>
              )
            }
          </Loadable>
        </div>
      </div>
    </div>
  )
}
