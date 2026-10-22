import { type ComponentType, memo } from 'react'

import { RichBoundary } from '@/components/assistant-ui/embeds/rich-boundary'
import { type DocBlockKind, parseCards, parseChart, parseQuadrant } from '@/lib/harvis-doc-blocks'
import { parseCsv, parseFlow } from '@/lib/harvis-doc-flow'
import { parseTimeline } from '@/lib/harvis-doc-timeline'

import { CardsBlock } from './cards-block'
import { ChartBlock } from './chart-block'
import { DocCodeFence } from './code-fence'
import { CsvBlock } from './csv-block'
import { FlowBlock } from './flow-block'
import { QuadrantBlock } from './quadrant-block'
import { TimelineBlock } from './timeline-block'

const BLOCKS: Record<DocBlockKind, ComponentType<{ code: string }>> = {
  cards: CardsBlock,
  chart: ChartBlock,
  csv: CsvBlock,
  flow: FlowBlock,
  quadrant: QuadrantBlock,
  timeline: TimelineBlock
}

/** True when every line of the body was malformed, so there is nothing to draw. */
export function isEmptyBlock(kind: DocBlockKind, code: string): boolean {
  try {
    return isEmpty(kind, code)
  } catch {
    // The raw-text card is the safe reading of a body no parser could take.
    return true
  }
}

function isEmpty(kind: DocBlockKind, code: string): boolean {
  switch (kind) {
    case 'cards':
      return !parseCards(code).length
    case 'chart':
      return !parseChart(code).rows.length
    case 'csv':
      return !parseCsv(code).header.length
    case 'flow':
      return !parseFlow(code).nodes.length
    case 'quadrant':
      return !parseQuadrant(code).cells.some(c => c.name || c.items.length)
    case 'timeline':
      return !parseTimeline(code).items.length
  }
}

/**
 * A finished block. A body that reads as nothing or a renderer that throws
 * falls back to the raw text as a code card, so a bad block never blanks the
 * document.
 */
export const DocBlock = memo(function DocBlock({ code, kind }: { code: string; kind: DocBlockKind }) {
  const Block = BLOCKS[kind]
  const raw = <DocCodeFence code={code} language={kind} />

  return isEmptyBlock(kind, code) ? (
    raw
  ) : (
    <RichBoundary fallback={raw} resetKey={code}>
      <Block code={code} />
    </RichBoundary>
  )
})
