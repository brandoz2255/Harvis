import { useMemo } from 'react'

import { useI18n } from '@/i18n'
import { parseTimeline, timelineRange, weekTicks } from '@/lib/harvis-doc-timeline'

import { BlockFrame } from './block-frame'
import { clip } from './palette'

const W = 640
const LABEL_W = 150
const X0 = LABEL_W + 16
const X1 = W - 14
const ROW = 30
const BAR = 14
const CHAR_PX = 5.8

type DatePlace = 'clamp' | 'inside' | 'left' | 'right'

/** Where a date label goes: beside the shape, else on the other side, else inside a wide bar; never over the label column. */
function placeDate(start: number, end: number, span: boolean, textW: number): DatePlace {
  const gap = span ? 8 : 12

  if (end + gap + textW <= W - 4) {
    return 'right'
  }

  if (start - gap - textW >= X0) {
    return 'left'
  }

  return span && end - start >= textW + 16 ? 'inside' : 'clamp'
}

/** Bars for spans, diamonds for milestones, week ticks across the top when every date parses. */
export function TimelineBlock({ code }: { code: string }) {
  const { t } = useI18n()
  const timeline = useMemo(() => parseTimeline(code), [code])
  const { items, scaled } = timeline

  const layout = useMemo(() => {
    const range = timelineRange(timeline)
    const ticks = scaled ? weekTicks(range.min, range.max) : []
    const slot = (X1 - X0) / Math.max(1, items.length)
    const at = (ms: number) => X0 + ((ms - range.min) / (range.max - range.min)) * (X1 - X0)

    return { at, slot, ticks }
  }, [items.length, scaled, timeline])

  if (!items.length) {
    return null
  }

  const top = scaled ? 28 : 8
  const height = top + items.length * ROW + 8

  return (
    <BlockFrame kind="timeline" subtitle={timeline.subtitle} title={timeline.title}>
      <svg
        aria-label={timeline.title || t.docPreview.blocks.timeline}
        className="block h-auto w-full"
        data-scaled={scaled}
        role="img"
        viewBox={`0 0 ${W} ${height}`}
      >
        {layout.ticks.map(tick => {
          const x = layout.at(tick.ms)

          return (
            <g data-slot="timeline-tick" key={tick.ms}>
              <line className="stroke-border" strokeDasharray="2 3" x1={x} x2={x} y1={20} y2={height - 4} />
              <text
                className="fill-muted-foreground"
                fontSize={10.5}
                textAnchor={x > X1 - 18 ? 'end' : 'middle'}
                x={x > X1 - 18 ? W - 4 : x}
                y={14}
              >
                {tick.label}
              </text>
            </g>
          )
        })}
        {items.map((item, i) => {
          const cy = top + i * ROW + ROW / 2
          const center = X0 + (i + 0.5) * layout.slot
          const start =
            scaled && item.start !== null ? layout.at(item.start) : center - (item.span ? layout.slot * 0.4 : 0)
          const rawEnd = scaled && item.end !== null ? layout.at(item.end) : center + layout.slot * 0.4
          const end = item.span ? Math.max(rawEnd, start + 8) : start
          const dateText = item.span ? t.docPreview.blocks.range(item.startText, item.endText) : item.startText
          const textW = dateText.length * CHAR_PX
          const gap = item.span ? 8 : 12
          const place = placeDate(start, end, item.span, textW)
          const dateX = { clamp: Math.max(X0, W - 4 - textW), inside: end - 8, left: start - gap, right: end + gap }[
            place
          ]
          const onBar = place === 'inside' && item.key
          const tone = item.key ? 'fill-primary' : 'fill-foreground/70'

          return (
            <g data-key={item.key || undefined} data-slot={item.span ? 'timeline-bar' : 'timeline-milestone'} key={i}>
              <title>{`${item.label}${dateText ? ` (${dateText})` : ''}`}</title>
              <text
                className={item.key ? 'fill-primary' : 'fill-foreground'}
                fontSize={12.5}
                fontWeight={item.key ? 700 : 500}
                x={8}
                y={cy + 4}
              >
                {clip(item.label, 24)}
              </text>
              {item.span ? (
                <rect
                  className={item.key ? 'fill-primary' : 'fill-foreground/20 stroke-foreground/30'}
                  height={BAR}
                  rx={BAR / 2}
                  width={end - start}
                  x={start}
                  y={cy - BAR / 2}
                />
              ) : (
                <polygon
                  className={tone}
                  points={`${start},${cy - 8} ${start + 8},${cy} ${start},${cy + 8} ${start - 8},${cy}`}
                />
              )}
              {dateText && (
                <text
                  className={onBar ? 'fill-primary-foreground' : item.key ? 'fill-primary' : 'fill-muted-foreground'}
                  fontSize={11}
                  fontWeight={item.key ? 600 : 400}
                  textAnchor={place === 'left' || place === 'inside' ? 'end' : 'start'}
                  x={dateX}
                  y={cy + 4}
                >
                  {dateText}
                </text>
              )}
            </g>
          )
        })}
      </svg>
    </BlockFrame>
  )
}
