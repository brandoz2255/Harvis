import { useMemo } from 'react'

import { useI18n } from '@/i18n'
import { parseCsv } from '@/lib/harvis-doc-flow'
import { cn } from '@/lib/utils'

import { BlockFrame } from './block-frame'
import { StatusText } from './status-chip'

const MAX_ROWS = 200
const NUMBER_RE = /^[-+]?[$€£¥]?\d[\d,]*(\.\d+)?%?$/
const CELL = 'max-w-64 truncate border-r border-b border-border/60 px-2 py-1 text-[0.6875rem]'

/** CSV as a grid (header row sticky) with the raw text under a collapsible Source. */
export function CsvBlock({ code }: { code: string }) {
  const { t } = useI18n()
  const copy = t.docPreview.blocks
  const table = useMemo(() => parseCsv(code), [code])

  if (!table.header.length) {
    return null
  }

  const shown = table.rows.slice(0, MAX_ROWS)

  return (
    <BlockFrame kind="csv">
      <div className="max-h-80 overflow-auto rounded-md border border-border/60" data-slot="csv-grid">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              {table.header.map((cell, c) => (
                <th className={cn(CELL, 'sticky top-0 bg-muted text-left font-medium text-muted-foreground')} key={c}>
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td className={cn(CELL, NUMBER_RE.test(cell) && 'text-right tabular-nums')} key={c} title={cell}>
                    <StatusText>{cell}</StatusText>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.rows.length > shown.length && (
        <div className="mt-1 text-[0.7em] text-muted-foreground">{copy.moreRows(table.rows.length - shown.length)}</div>
      )}
      <details className="mt-2 text-[0.8em]" data-slot="csv-source">
        <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">
          {copy.source}
        </summary>
        <pre className="mt-1 max-h-60 overflow-auto rounded-md bg-muted/40 p-2 font-mono text-[0.9em] leading-relaxed">
          {code.trim()}
        </pre>
      </details>
    </BlockFrame>
  )
}
