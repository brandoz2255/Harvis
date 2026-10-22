import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { useI18n } from '@/i18n'
import { columnLetter, sheetCellDisplay } from '@/lib/harvis-doc'
import { cn } from '@/lib/utils'

import type { DocPart } from './preview-document-parts'
import { type ViewProps, WritingCaret } from './preview-document-views'

const MIN_COLUMNS = 5
const MIN_ROWS = 12
const NUMBER_RE = /^[-+]?[$€£¥]?\d[\d,]*(\.\d+)?%?$/

const CELL = 'h-6 max-w-64 min-w-20 truncate border-r border-b border-border/60 px-2 text-[0.6875rem]'
const AXIS = 'sticky z-10 bg-muted text-center font-medium text-muted-foreground select-none'

interface Selection {
  col: number
  row: number
  sheet: number
}

function isFormula(value: string): boolean {
  return value.startsWith('=')
}

function SheetSkeleton({ name }: { name: string }) {
  const { t } = useI18n()

  return (
    <div className="grid gap-2 p-3" data-slot="doc-skeleton">
      <div className="text-[0.625rem] font-medium text-muted-foreground italic">{t.docPreview.pending(name)}</div>
      <div className="grid gap-px" style={{ gridTemplateColumns: 'repeat(6, minmax(0, 1fr))' }}>
        {Array.from({ length: 6 * 8 }, (_, i) => (
          <div
            className={cn(
              'h-5 rounded-sm animate-pulse motion-reduce:animate-none',
              i < 6 ? 'bg-muted' : 'bg-muted/40'
            )}
            key={`cell-${i}`}
          />
        ))}
      </div>
    </div>
  )
}

function SheetTabs({ active, onPick, parts }: { active: number; onPick: (index: number) => void; parts: DocPart[] }) {
  const { t } = useI18n()

  return (
    <div
      aria-label={t.docPreview.sheetTabs}
      className="flex shrink-0 gap-px overflow-x-auto border-t border-border/60 bg-muted/30 px-2"
      role="tablist"
    >
      {parts.map((part, i) => {
        const pending = part.state === 'pending'

        return (
          <button
            aria-selected={i === active}
            className={cn(
              'max-w-40 shrink-0 truncate border-t-2 px-3 py-1 text-[0.6875rem] transition-colors',
              i === active ? 'border-primary bg-background font-semibold text-foreground' : 'border-transparent',
              pending ? 'cursor-default text-muted-foreground/60 italic' : 'text-muted-foreground hover:text-foreground'
            )}
            disabled={pending}
            key={`tab-${i}`}
            onClick={() => onPick(i)}
            role="tab"
            title={pending ? t.docPreview.pending(part.label) : undefined}
            type="button"
          >
            {part.label || `Sheet${i + 1}`}
          </button>
        )
      })}
    </div>
  )
}

/**
 * Spreadsheet view: one tab per sheet, the live sheet followed while it is
 * written, a formula bar and an A1-style grid padded to a usable minimum so a
 * three-row table still looks like a sheet.
 */
export function SheetView({ doc, parts, streaming }: ViewProps) {
  const { t } = useI18n()
  const copy = t.docPreview
  const gridRef = useRef<HTMLDivElement>(null)
  const [picked, setPicked] = useState<null | number>(null)
  const [selection, setSelection] = useState<null | Selection>(null)

  const live = parts.findIndex(part => part.state === 'active')
  const lastWritten = doc.sheets.length - 1
  // Follow the sheet being written, until the reader opens another one.
  const active = picked !== null && picked <= lastWritten ? picked : Math.max(0, live >= 0 ? live : lastWritten)
  const sheet = doc.sheets[active]
  const rows = sheet?.rows ?? []
  const columns = Math.max(MIN_COLUMNS, ...rows.map(row => row.length))
  const rowCount = Math.max(MIN_ROWS, rows.length)
  const following = picked === null && streaming
  const signature = `${active}:${rows.length}:${rows[rows.length - 1]?.join('|') ?? ''}`

  useLayoutEffect(() => {
    const grid = gridRef.current

    if (following && grid) {
      grid.scrollTop = grid.scrollHeight
    }
  }, [following, signature])

  useEffect(() => {
    if (!streaming) {
      setPicked(null)
    }
  }, [streaming])

  const selected = selection && selection.sheet === active ? selection : null
  const selectedValue = selected ? (rows[selected.row]?.[selected.col] ?? '') : ''
  const lastRow = rows.length - 1
  const lastCol = rows[lastRow] ? rows[lastRow].length - 1 : -1
  const showCaret = streaming && live === active

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border/60 px-2 py-1" data-slot="doc-formula-bar">
        <span
          aria-label={copy.formulaBar}
          className="w-12 shrink-0 rounded border border-border/60 px-1.5 py-0.5 text-center text-[0.625rem] tabular-nums text-muted-foreground"
        >
          {selected ? `${columnLetter(selected.col)}${selected.row + 1}` : ''}
        </span>
        <span className="shrink-0 text-[0.625rem] font-semibold text-muted-foreground italic">fx</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[0.6875rem] text-foreground">{selectedValue}</span>
      </div>
      {!sheet ? (
        <div className="min-h-0 flex-1 overflow-auto">
          {streaming ? (
            <SheetSkeleton name={parts[0]?.label || copy.untitled} />
          ) : (
            <div className="p-6 text-center text-xs text-muted-foreground">{copy.emptySheet}</div>
          )}
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto" ref={gridRef}>
          <table className="border-separate border-spacing-0" data-slot="doc-grid">
            <thead>
              <tr>
                <th className={cn(AXIS, 'top-0 left-0 z-20 h-5 w-9 border-r border-b border-border/60')} />
                {Array.from({ length: columns }, (_, c) => (
                  <th
                    className={cn(AXIS, 'top-0 h-5 border-r border-b border-border/60 text-[0.625rem]')}
                    key={`col-${c}`}
                  >
                    {columnLetter(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: rowCount }, (_, r) => (
                <tr key={`row-${r}`}>
                  <th className={cn(AXIS, 'left-0 w-9 border-r border-b border-border/60 text-[0.625rem]')}>{r + 1}</th>
                  {Array.from({ length: columns }, (_, c) => {
                    const { bold, text: value } = sheetCellDisplay(rows[r]?.[c] ?? '')
                    const formula = isFormula(value)
                    const isSelected = selected?.row === r && selected.col === c

                    return (
                      <td
                        className={cn(
                          CELL,
                          r === 0 && rows.length > 0 && 'bg-muted/50 font-semibold text-muted-foreground',
                          bold && 'font-semibold',
                          !formula && NUMBER_RE.test(value) && 'text-right tabular-nums',
                          isSelected && 'outline-2 -outline-offset-1 outline-primary'
                        )}
                        key={`cell-${r}-${c}`}
                        onClick={() => setSelection({ col: c, row: r, sheet: active })}
                      >
                        {formula && <span className="mr-1 text-[0.5625rem] font-semibold text-primary italic">fx</span>}
                        {value}
                        {showCaret && r === lastRow && c === lastCol && <WritingCaret />}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <SheetTabs active={active} onPick={setPicked} parts={parts} />
    </div>
  )
}
