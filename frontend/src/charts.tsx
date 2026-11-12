import { useState } from 'react'
import type { ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { Bar as PriceBar, Card } from './api'
import { fmt } from './api'

const AXIS = { fill: 'var(--text-muted)', fontSize: 11 }

const ACTIVE_DOT = { r: 4, stroke: 'var(--surface-1)', strokeWidth: 2 }

interface TipRow {
  name?: string | number
  value?: unknown
  color?: string
  dataKey?: unknown
}

function Tip({
  active,
  payload,
  label,
  format,
}: {
  active?: boolean
  payload?: readonly TipRow[]
  label?: ReactNode
  format: (v: number, key: string) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="tooltip">
      <div className="t">{label}</div>
      {payload.map((p) => (
        <div className="r" key={String(p.dataKey)}>
          <span>
            <span className="legend">
              <span className="sw" style={{ background: p.color }} />
            </span>
            {p.name}
          </span>
          <b>{typeof p.value === 'number' ? format(p.value, String(p.dataKey)) : '—'}</b>
        </div>
      ))}
    </div>
  )
}

// Label only the last point of a line, in text ink (not the series color)
function endLabel(name: string, lastIndex: number) {
  return (props: { x?: number | string; y?: number | string; index?: number }) => {
    if (props.index !== lastIndex || props.x == null || props.y == null) return <g />
    return (
      <text x={Number(props.x) + 6} y={Number(props.y)} dy={4} fontSize={11} fill="var(--text-secondary)">
        {name}
      </text>
    )
  }
}

export function ChartOrTable({ chart, table }: { chart: ReactNode; table: ReactNode }) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  return (
    <div>
      <div className="row" style={{ justifyContent: 'flex-end', marginBottom: 4 }}>
        <button className="link small" onClick={() => setView(view === 'chart' ? 'table' : 'chart')}>
          {view === 'chart' ? 'Show as table' : 'Show as chart'}
        </button>
      </div>
      {view === 'chart' ? chart : <div className="table-wrap" style={{ maxHeight: 320 }}>{table}</div>}
    </div>
  )
}

// --- Price with card levels ------------------------------------------------

const PRICE_SERIES = [
  { key: 'close', name: 'Close', color: 'var(--series-1)' },
  { key: 'sma_20', name: '20-day avg', color: 'var(--series-2)' },
  { key: 'sma_50', name: '50-day avg', color: 'var(--series-3)' },
] as const

export function PriceChart({ bars, card }: { bars: PriceBar[]; card?: Card }) {
  const levels = card
    ? [
        { y: card.target_2, label: `T2 ${fmt.inr(card.target_2)}` },
        { y: card.target_1, label: `T1 ${fmt.inr(card.target_1)}` },
        { y: card.entry_zone[0], label: `Entry ${fmt.inr(card.entry_zone[0])}` },
        { y: card.stop_loss, label: `Stop ${fmt.inr(card.stop_loss)}` },
      ].filter((l): l is { y: number; label: string } => l.y != null)
    : []

  const values = bars.flatMap((b) => [b.low, b.high]).concat(levels.map((l) => l.y))
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const pad = (hi - lo) * 0.04

  const last = bars.length - 1

  return (
    <ChartOrTable
      chart={
        <>
          <div className="legend">
            {PRICE_SERIES.map((s) => (
              <span key={s.key}>
                <span className="sw" style={{ background: s.color }} />
                {s.name}
              </span>
            ))}
            {levels.length > 0 && (
              <span>
                <span className="sw dash" />
                Card levels (targets, entry, stop)
              </span>
            )}
          </div>
          <div className="chart">
            <ResponsiveContainer>
              <LineChart data={bars} margin={{ top: 8, right: 110, bottom: 0, left: 4 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} minTickGap={48} />
                <YAxis
                  domain={[lo - pad, hi + pad]}
                  tick={AXIS}
                  tickLine={false}
                  axisLine={false}
                  width={64}
                  tickFormatter={(v: number) => fmt.num(Math.round(v))}
                />
                <Tooltip
                  cursor={{ stroke: 'var(--text-muted)', strokeWidth: 1 }}
                  content={(p) => <Tip {...p} format={(v) => fmt.inr(v)} />}
                />
                {levels.map((l) => (
                  <ReferenceLine
                    key={l.label}
                    y={l.y}
                    stroke="var(--text-muted)"
                    strokeDasharray="4 4"
                    ifOverflow="extendDomain"
                    label={{ value: l.label, position: 'right', fill: 'var(--text-secondary)', fontSize: 11 }}
                  />
                ))}
                {PRICE_SERIES.map((s) => (
                  <Line
                    key={s.key}
                    dataKey={s.key}
                    name={s.name}
                    stroke={s.color}
                    strokeWidth={2}
                    dot={false}
                    activeDot={ACTIVE_DOT}
                    isAnimationActive={false}
                    connectNulls
                    label={card ? undefined : endLabel(s.name, last)}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th className="num">Open</th>
              <th className="num">High</th>
              <th className="num">Low</th>
              <th className="num">Close</th>
              <th className="num">20-day avg</th>
              <th className="num">50-day avg</th>
            </tr>
          </thead>
          <tbody>
            {[...bars].reverse().map((b) => (
              <tr key={b.date}>
                <td>{b.date}</td>
                <td className="num">{fmt.num(b.open)}</td>
                <td className="num">{fmt.num(b.high)}</td>
                <td className="num">{fmt.num(b.low)}</td>
                <td className="num">{fmt.num(b.close)}</td>
                <td className="num">{fmt.num(b.sma_20)}</td>
                <td className="num">{fmt.num(b.sma_50)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  )
}

// --- Diverging horizontal bars (e.g. sector returns) ------------------------

interface ShapeProps {
  x?: number
  y?: number
  width?: number
  height?: number
  value?: number | number[]
}

// Rounded (4px) only at the data end; flat against the zero baseline
function DivergingBar(props: ShapeProps & { fill?: string }) {
  const { x = 0, y = 0, width = 0, height = 0, fill } = props
  const left = Math.min(x, x + width)
  const w = Math.abs(width)
  const r = Math.min(4, w, height / 2)
  const raw = Array.isArray(props.value) ? props.value[1] - props.value[0] : props.value ?? 0
  const right = left + w
  const bottom = y + height
  const d =
    raw >= 0
      ? `M${left},${y} H${right - r} Q${right},${y} ${right},${y + r} V${bottom - r} Q${right},${bottom} ${right - r},${bottom} H${left} Z`
      : `M${right},${y} H${left + r} Q${left},${y} ${left},${y + r} V${bottom - r} Q${left},${bottom} ${left + r},${bottom} H${right} Z`
  return <path d={d} fill={fill} />
}

export function DivergingBars({
  data,
  valueLabel,
}: {
  data: { label: string; value: number; extra?: string }[]
  valueLabel: string
}) {
  const height = Math.max(200, data.length * 28 + 30)

  return (
    <ChartOrTable
      chart={
        <>
          <div className="legend">
            <span>
              <span className="sw" style={{ background: 'var(--pos)' }} />
              Up
            </span>
            <span>
              <span className="sw" style={{ background: 'var(--neg)' }} />
              Down
            </span>
          </div>
          <div style={{ width: '100%', height }}>
            <ResponsiveContainer>
              <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }} barCategoryGap={4}>
                <CartesianGrid horizontal={false} stroke="var(--grid)" />
                <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} tickFormatter={(v: number) => `${v}%`} />
                <YAxis type="category" dataKey="label" tick={AXIS} tickLine={false} axisLine={false} width={150} />
                <ReferenceLine x={0} stroke="var(--text-muted)" />
                <Tooltip
                  cursor={{ fill: 'var(--surface-2)' }}
                  content={(p) => <Tip {...p} format={(v) => fmt.signedPct(v)} />}
                />
                <Bar dataKey="value" name={valueLabel} shape={DivergingBar} isAnimationActive={false}>
                  {data.map((d) => (
                    <Cell key={d.label} fill={d.value >= 0 ? 'var(--pos)' : 'var(--neg)'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th className="num">{valueLabel}</th>
              {data.some((d) => d.extra) && <th className="num">Detail</th>}
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.label}>
                <td>{d.label}</td>
                <td className="num">{fmt.signedPct(d.value)}</td>
                {d.extra && <td className="num">{d.extra}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  )
}

// --- Equity curves -----------------------------------------------------------

const EQUITY_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']

export function EquityChart({
  dates,
  series,
}: {
  dates: string[]
  series: { name: string; values: (number | null)[] }[]
}) {
  // Plot cumulative return in %, one row per date
  const data = dates.map((d, i) => {
    const row: Record<string, string | number | null> = { date: d }
    series.forEach((s, j) => {
      const v = s.values[i]
      row[`s${j}`] = v == null ? null : Math.round((v - 1) * 10000) / 100
    })
    return row
  })

  const last = data.length - 1

  return (
    <ChartOrTable
      chart={
        <>
          <div className="legend">
            {series.map((s, j) => (
              <span key={s.name}>
                <span className="sw" style={{ background: EQUITY_COLORS[j] }} />
                {s.name}
              </span>
            ))}
          </div>
          <div className="chart">
            <ResponsiveContainer>
              <LineChart data={data} margin={{ top: 8, right: 150, bottom: 0, left: 4 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} minTickGap={48} />
                <YAxis tick={AXIS} tickLine={false} axisLine={false} width={48} tickFormatter={(v: number) => `${v}%`} />
                <ReferenceLine y={0} stroke="var(--text-muted)" />
                <Tooltip
                  cursor={{ stroke: 'var(--text-muted)', strokeWidth: 1 }}
                  content={(p) => <Tip {...p} format={(v) => fmt.signedPct(v, 1)} />}
                />
                {series.map((s, j) => (
                  <Line
                    key={s.name}
                    dataKey={`s${j}`}
                    name={s.name}
                    stroke={EQUITY_COLORS[j]}
                    strokeWidth={2}
                    dot={false}
                    activeDot={ACTIVE_DOT}
                    isAnimationActive={false}
                    connectNulls
                    label={endLabel(s.name.length > 22 ? `${s.name.slice(0, 21)}…` : s.name, last)}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th>Date</th>
              {series.map((s) => (
                <th className="num" key={s.name}>{s.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...data].reverse().map((r) => (
              <tr key={String(r.date)}>
                <td>{r.date}</td>
                {series.map((_, j) => (
                  <td className="num" key={j}>{fmt.signedPct(r[`s${j}`] as number | null, 1)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  )
}
