import type { ReactNode } from 'react'
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'

import { api } from './api'
import { useApi } from './hooks'
import Dashboard from './pages/Dashboard'
import Portfolio from './pages/Portfolio'
import Research from './pages/Research'
import Screener from './pages/Screener'
import StockDetail from './pages/StockDetail'

const NAV = [
  { to: '/', label: 'Market' },
  { to: '/screener', label: 'AI Screener' },
  { to: '/stock/RELIANCE', label: 'Deep Dive' },
  { to: '/research', label: 'News + Research' },
  { to: '/portfolio', label: 'Backtest + Portfolio' },
]

function Layout({ children }: { children: ReactNode }) {
  const health = useApi(api.health)

  const prices = health.data?.data.stock_prices
  const llmOff = health.data && health.data.llm !== 'configured'

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          Indian AI Stock <span>Intelligence v1</span>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="spacer" />
        <span className="small muted">
          {health.error ? 'API offline' : prices ? `Data as of ${prices.slice(0, 10)}` : ''}
        </span>
      </header>
      <main>
        {health.error && (
          <div className="notice" style={{ marginBottom: 16 }}>
            Can't reach the API. Start it from <code>backend/</code> with{' '}
            <code>uvicorn app.main:app --reload</code>.
          </div>
        )}
        {llmOff && (
          <div className="notice" style={{ marginBottom: 16 }}>
            LLM not configured: news sentiment, AI explanations and research answers are off. Add{' '}
            <code>OPENAI_API_KEY</code> to <code>backend/.env</code> and restart the API.
          </div>
        )}
        {children}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/screener" element={<Screener />} />
          <Route path="/stock/:symbol" element={<StockDetail />} />
          <Route path="/research" element={<Research />} />
          <Route path="/portfolio" element={<Portfolio />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
