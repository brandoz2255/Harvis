import { useMemo } from 'react'

import { useI18n } from '@/i18n'
import { type ChartData, formatChartValue, parseChart } from '@/lib/harvis-doc-blocks'

import { BlockFrame } from './block-frame'
import { clip, seriesColor } from './palette'

const W = 640
const H = 236
const PLOT = { bottom: 206, left: 52, right: 628, top: 18 }

/** Gridline values: round steps (1, 2, 5 x 10^n) that cover the data and always include zero. */
export function niceScale(min: number, max: number, count = 4): { hi: number; lo: number; step: number } {
  const lo0 = Math.min(0, min)
  const hi0 = Math.max(0, max)
  const span = hi0 - lo0 || 1
  const raw = span / count
  const pow = 10 ** Math.floor(Math.log10(raw))
  const norm = raw / pow
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * pow

  const lo = Math.floor(lo0 / step) * step
  const hi = Math.ceil(hi0 / step) * step

  // All-zero data would leave no vertical range to scale into.
  return { hi: hi === lo ? lo + step : hi, lo, step }
}

function Legend({ series }: { series: string[] }) {
  return (
    <ul className="mb-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[0.75em] text-muted-foreground" data-slot="chart-legend">
      {series.map((name, i) => (
        <li className="flex items-center gap-1.5" key={i}>
          <span className="size-2 rounded-sm" style={{ background: seriesColor(i) }} />
          {name}
        </li>
      ))}
    </ul>
  )
}

function Plot({ chart }: { chart: ChartData }) {
  const all = chart.rows.flatMap(r => r.values)
  const { hi, lo, step } = niceScale(Math.min(...all), Math.max(...all))
  const y = (v: number) => PLOT.bottom - ((v - lo) / (hi - lo)) * (PLOT.bottom - PLOT.top)
  const slot = (PLOT.right - PLOT.left) / chart.rows.length
  const zero = y(0)
  const lines: number[] = []

  for (let v = lo; v <= hi + step / 2; v += step) {
    lines.push(Math.round(v * 1e6) / 1e6)
  }

  const fmt = (v: number) => formatChartValue(v, chart.prefix, chart.suffix)
  const perGroup = chart.series.length
  const barW = Math.min(36, (slot * 0.72) / perGroup)
  const labelled = barW >= 16 || (perGroup === 1 && slot >= 30)
  const maxLabel = Math.max(3, Math.floor(slot / 6))

  return (
    <>
      <g data-slot="chart-grid">
        {lines.map(v => (
          <g key={v}>
            <line
              className={v === 0 ? 'stroke-foreground/40' : 'stroke-border'}
              x1={PLOT.left}
              x2={PLOT.right}
              y1={y(v)}
              y2={y(v)}
            />
            <text className="fill-muted-foreground" fontSize={10.5} textAnchor="end" x={PLOT.left - 6} y={y(v) + 3.5}>
              {fmt(v)}
            </text>
          </g>
        ))}
      </g>
      {chart.rows.map((row, i) => {
        const cx = PLOT.left + (i + 0.5) * slot

        return (
          <text
            className="fill-muted-foreground"
            fontSize={11}
            key={`x-${i}`}
            textAnchor="middle"
            x={cx}
            y={PLOT.bottom + 16}
          >
            <title>{row.label}</title>
            {clip(row.label, maxLabel)}
          </text>
        )
      })}
      {chart.type === 'bar' &&
        chart.rows.map((row, i) => {
          const left = PLOT.left + (i + 0.5) * slot - (barW * perGroup) / 2

          return row.values.map((value, s) => {
            const top = Math.min(y(value), zero)

            return (
              <g data-slot="chart-bar" key={`${i}-${s}`}>
                <rect
                  fill={seriesColor(s)}
                  height={Math.max(1, Math.abs(zero - y(value)))}
                  rx={2}
                  width={barW - 2}
                  x={left + s * barW}
                  y={top}
                />
                {labelled && (
                  <text
                    className="fill-foreground"
                    fontSize={10.5}
                    textAnchor="middle"
                    x={left + s * barW + (barW - 2) / 2}
                    y={value >= 0 ? top - 4 : top + Math.abs(zero - y(value)) + 11}
                  >
                    {fmt(value)}
                  </text>
                )}
              </g>
            )
          })
        })}
      {chart.type === 'line' &&
        chart.series.map((_, s) => {
          const pts = chart.rows.map((row, i) => [PLOT.left + (i + 0.5) * slot, y(row.values[s] ?? 0)] as const)

          return (
            <g data-slot="chart-line" key={s}>
              <polyline
                fill="none"
                points={pts.map(p => p.join(',')).join(' ')}
                stroke={seriesColor(s)}
                strokeLinejoin="round"
                strokeWidth={2.2}
              />
              {pts.map(([px, py], i) => (
                <g key={i}>
                  <circle cx={px} cy={py} fill={seriesColor(s)} r={3.2} />
                  {chart.rows.length <= 14 && (
                    <text className="fill-foreground" fontSize={10.5} textAnchor="middle" x={px} y={py - 8}>
                      {fmt(chart.rows[i].values[s] ?? 0)}
                    </text>
                  )}
                </g>
              ))}
            </g>
          )
        })}
    </>
  )
}

function PieChart({ chart }: { chart: ChartData }) {
  const rows = chart.rows.map(r => ({ label: r.label, value: Math.max(0, r.values[0] ?? 0) }))
  const total = rows.reduce((sum, r) => sum + r.value, 0)
  const [cx, cy, r] = [120, 110, 92]
  const step = Math.min(22, 200 / rows.length)
  let angle = -Math.PI / 2

  const point = (a: number) => `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`

  return (
    <>
      {rows.map((row, i) => {
        const sweep = total ? (row.value / total) * Math.PI * 2 : 0
        const [from, to] = [angle, angle + sweep]

        angle = to

        const shape =
          sweep >= Math.PI * 2 - 1e-6 ? (
            <circle cx={cx} cy={cy} fill={seriesColor(i)} r={r} />
          ) : sweep > 0 ? (
            <path
              d={`M${cx},${cy} L${point(from)} A${r},${r} 0 ${sweep > Math.PI ? 1 : 0} 1 ${point(to)} Z`}
              fill={seriesColor(i)}
              stroke="var(--color-card)"
              strokeWidth={1.5}
            />
          ) : null

        return (
          <g data-slot="chart-slice" key={i}>
            {shape}
            <rect fill={seriesColor(i)} height={9} rx={2} width={9} x={250} y={22 + i * step - 8} />
            <text className="fill-foreground" fontSize={12} x={266} y={22 + i * step}>
              {clip(row.label, 30)}
              <tspan className="fill-muted-foreground" dx={8}>
                {formatChartValue(row.value, chart.prefix, chart.suffix)}
                {total ? ` · ${Math.round((row.value / total) * 100)}%` : ''}
              </tspan>
            </text>
          </g>
        )
      })}
    </>
  )
}

/** Bar (grouped when there are several series), line or pie, drawn as inline SVG. */
export function ChartBlock({ code }: { code: string }) {
  const { t } = useI18n()
  const chart = useMemo(() => parseChart(code), [code])

  if (!chart.rows.length) {
    return null
  }

  const pie = chart.type === 'pie'
  const height = pie ? Math.max(210, 30 + chart.rows.length * Math.min(22, 200 / chart.rows.length)) : H

  return (
    <BlockFrame kind="chart" title={chart.title}>
      {!pie && chart.series.length > 1 && <Legend series={chart.series} />}
      <svg
        aria-label={chart.title || t.docPreview.blocks.chart}
        className="block h-auto w-full"
        data-type={chart.type}
        role="img"
        viewBox={`0 0 ${W} ${height}`}
      >
        {pie ? <PieChart chart={chart} /> : <Plot chart={chart} />}
      </svg>
    </BlockFrame>
  )
}
