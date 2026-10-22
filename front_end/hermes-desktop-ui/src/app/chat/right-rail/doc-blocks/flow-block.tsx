import { useId, useMemo } from 'react'

import { useI18n } from '@/i18n'
import { parseFlow } from '@/lib/harvis-doc-flow'

import { BlockFrame } from './block-frame'
import { clip } from './palette'

const BOX_H = 36
const ROW_GAP = 24
const COL_GAP = 60
const PAD = 10
const CHAR_PX = 7

function boxWidth(label: string): number {
  return Math.min(176, Math.max(72, Math.min(label.length, 24) * CHAR_PX + 26))
}

/** Boxes in columns (longest path from a source) joined by arrows; a cycle's closing edge loops underneath, dashed. */
export function FlowBlock({ code }: { code: string }) {
  const { t } = useI18n()
  const marker = `arrow-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const flow = useMemo(() => parseFlow(code), [code])

  const geometry = useMemo(() => {
    const widths = Array.from({ length: flow.layers }, (_, layer) =>
      Math.max(...flow.nodes.filter(n => n.layer === layer).map(n => boxWidth(n.id)))
    )

    const counts = Array.from({ length: flow.layers }, (_, layer) => flow.nodes.filter(n => n.layer === layer).length)
    const tallest = Math.max(1, ...counts)
    const left = widths.map((_, i) => PAD + widths.slice(0, i).reduce((sum, w) => sum + w + COL_GAP, 0))
    const stride = BOX_H + ROW_GAP
    const back = flow.edges.some(e => e.back)

    const boxes = new Map(
      flow.nodes.map(n => {
        const w = boxWidth(n.id)
        const x = left[n.layer] + (widths[n.layer] - w) / 2
        const y = PAD + n.row * stride + ((tallest - counts[n.layer]) * stride) / 2

        return [n.id, { w, x, y }] as const
      })
    )

    return {
      boxes,
      height: PAD * 2 + tallest * stride - ROW_GAP + (back ? 40 : 0),
      width: PAD * 2 + widths.reduce((sum, w) => sum + w, 0) + COL_GAP * Math.max(0, widths.length - 1)
    }
  }, [flow])

  if (!flow.nodes.length) {
    return null
  }

  return (
    <BlockFrame kind="flow">
      <svg
        aria-label={t.docPreview.blocks.flow}
        className="mx-auto block h-auto max-w-full"
        data-slot="flow-svg"
        role="img"
        style={{ width: geometry.width }}
        viewBox={`0 0 ${geometry.width} ${geometry.height}`}
      >
        <defs>
          <marker id={marker} markerHeight={8} markerWidth={8} orient="auto-start-reverse" refX={7} refY={4}>
            <path d="M0,0 L8,4 L0,8 z" style={{ fill: 'var(--color-muted-foreground)' }} />
          </marker>
        </defs>
        {flow.edges.map((edge, i) => {
          const a = geometry.boxes.get(edge.from)
          const b = geometry.boxes.get(edge.to)

          if (!a || !b) {
            return null
          }

          if (edge.back) {
            const [sx, tx] = [a.x + a.w / 2, b.x + b.w / 2]
            const y = Math.max(a.y, b.y) + BOX_H

            return (
              <path
                className="stroke-muted-foreground"
                d={`M${sx},${y} C${sx},${y + 34} ${tx},${y + 34} ${tx},${y + 1}`}
                data-back="true"
                data-slot="flow-edge"
                fill="none"
                key={i}
                markerEnd={`url(#${marker})`}
                strokeDasharray="4 3"
                strokeWidth={1.4}
              />
            )
          }

          const [x1, y1, x2, y2] = [a.x + a.w, a.y + BOX_H / 2, b.x, b.y + BOX_H / 2]
          const bend = Math.max(20, (x2 - x1) / 2)

          return (
            <path
              className="stroke-muted-foreground"
              d={`M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2 - 1},${y2}`}
              data-slot="flow-edge"
              fill="none"
              key={i}
              markerEnd={`url(#${marker})`}
              strokeWidth={1.4}
            />
          )
        })}
        {flow.nodes.map(node => {
          const box = geometry.boxes.get(node.id)

          return box ? (
            <g data-slot="flow-box" key={node.id}>
              <title>{node.id}</title>
              <rect
                className="fill-card stroke-border"
                height={BOX_H}
                rx={8}
                strokeWidth={1.2}
                width={box.w}
                x={box.x}
                y={box.y}
              />
              <text
                className="fill-foreground"
                dominantBaseline="central"
                fontSize={12.5}
                fontWeight={500}
                textAnchor="middle"
                x={box.x + box.w / 2}
                y={box.y + BOX_H / 2}
              >
                {clip(node.id, 24)}
              </text>
            </g>
          ) : null
        })}
      </svg>
    </BlockFrame>
  )
}
