import { useI18n } from '@/i18n'
import type { DocBlockKind } from '@/lib/harvis-doc-blocks'
import { cn } from '@/lib/utils'

const PULSE = 'animate-pulse motion-reduce:animate-none'

// Heights track the finished block so the document does not jump when it lands.
const HEIGHT: Record<DocBlockKind, string> = {
  cards: 'h-28',
  chart: 'h-60',
  csv: 'h-40',
  flow: 'h-40',
  quadrant: 'h-64',
  timeline: 'h-44'
}

/** Placeholder for a block whose closing fence has not arrived: caption plus pulsing bars, never partial output. */
export function BlockSkeleton({ kind }: { kind: DocBlockKind }) {
  const { t } = useI18n()
  const blocks = t.docPreview.blocks

  return (
    <div
      aria-busy="true"
      className={cn('my-[0.9em] grid content-between rounded-lg border border-dashed border-border p-3', HEIGHT[kind])}
      data-kind={kind}
      data-slot="doc-block-skeleton"
    >
      <div className="text-[0.75em] font-medium italic text-muted-foreground">{blocks.drawing(blocks[kind])}</div>
      <div className="grid gap-2">
        {['86%', '64%', '75%'].map(width => (
          <div className={cn('h-2.5 rounded bg-current/10', PULSE)} key={width} style={{ width }} />
        ))}
      </div>
    </div>
  )
}
