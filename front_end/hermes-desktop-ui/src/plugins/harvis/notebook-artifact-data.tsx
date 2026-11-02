/**
 * Two artifact viewers: a data table with CSV download, and a slide deck shown
 * as an outline with PowerPoint download. Both downloads are rebuilt by the
 * server from the stored artifact, so they match what is on screen.
 */

import { Button, cn, Codicon } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { type Artifact, exportUrl } from './notebook-artifacts'
import { errorText } from './notebook-shared'

/** The file name the server chose (`Content-Disposition`), else the fallback. */
export function filenameFrom(header: null | string, fallback: string): string {
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header ?? '')

  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      // fall through to the plain form
    }
  }

  return /filename="?([^";]+)"?/i.exec(header ?? '')?.[1] || fallback
}

/** Authed GET of an export route, saved through a temporary link. */
export async function downloadFile(url: string, fallbackName: string): Promise<void> {
  const res = await fetch(url, { credentials: 'include' })

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`

    try {
      const body = (await res.json()) as { detail?: unknown }

      if (typeof body.detail === 'string') {
        detail = body.detail
      }
    } catch {
      // non-JSON error body: keep the status line
    }

    throw new Error(detail)
  }

  const blob = await res.blob()
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')

  link.href = href
  link.download = filenameFrom(res.headers.get('content-disposition'), fallbackName)
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(href), 10_000)
}

function DownloadButton({ fallbackName, label, url }: { fallbackName: string; label: string; url: string }) {
  const [state, setState] = useState<'busy' | 'idle'>('idle')
  const [error, setError] = useState('')

  return (
    <span className="inline-flex items-center gap-2">
      <Button
        disabled={state === 'busy'}
        onClick={async () => {
          setState('busy')
          setError('')

          try {
            await downloadFile(url, fallbackName)
          } catch (err) {
            setError(errorText(err))
          } finally {
            setState('idle')
          }
        }}
        size="xs"
        variant="outline"
      >
        <Codicon name="cloud-download" size="0.8rem" /> {state === 'busy' ? 'Preparing…' : label}
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </span>
  )
}

export function DataTableView({ artifact, notebookId }: { artifact: Artifact; notebookId: string }) {
  const columns = artifact.content?.columns ?? []
  const rows = artifact.content?.rows ?? []
  const hasSource = rows.some(r => r.source)

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-left text-xs">
          <thead className="bg-(--ui-bg-tertiary)">
            <tr>
              {columns.map((c, i) => (
                <th className="px-2 py-1.5 font-medium" key={i} scope="col">
                  {c}
                </th>
              ))}
              {hasSource && (
                <th className="px-2 py-1.5 font-medium text-(--ui-text-tertiary)" scope="col">
                  Source
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((r, i) => (
              <tr key={i}>
                {columns.map((_, j) => (
                  <td className="px-2 py-1.5 align-top" key={j}>
                    {r.cells[j] ?? ''}
                  </td>
                ))}
                {hasSource && <td className="px-2 py-1.5 align-top text-(--ui-text-tertiary)">{r.source ?? ''}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-(--ui-text-tertiary)">
        {rows.length} row{rows.length === 1 ? '' : 's'}. The Source column is the model's note of where a row came from,
        not a checked citation.
      </p>
      <DownloadButton
        fallbackName="data-table.csv"
        label="Download CSV"
        url={exportUrl(notebookId, artifact.id, 'csv')}
      />
    </div>
  )
}

export function SlidesView({ artifact, notebookId }: { artifact: Artifact; notebookId: string }) {
  const slides = artifact.content?.slides ?? []
  const [index, setIndex] = useState(0)
  const slide = slides[Math.min(index, slides.length - 1)]

  return (
    <div className="space-y-2">
      <ol aria-label="Slide outline" className="space-y-0.5">
        {slides.map((s, i) => (
          <li key={i}>
            <button
              aria-current={slide === s}
              className={cn(
                'flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs',
                slide === s ? 'bg-(--ui-bg-tertiary) text-foreground' : 'text-(--ui-text-secondary) hover:bg-accent/60'
              )}
              onClick={() => setIndex(i)}
              type="button"
            >
              <span className="w-4 shrink-0 tabular-nums text-(--ui-text-tertiary)">{i + 1}</span>
              <span className="min-w-0 flex-1 truncate">{s.title}</span>
            </button>
          </li>
        ))}
      </ol>
      {slide && (
        <div className="aspect-video space-y-1.5 overflow-y-auto rounded-lg border bg-(--ui-bg-secondary) p-3">
          <h5 className="text-sm font-semibold">{slide.title}</h5>
          <ul className="list-disc space-y-1 pl-4 text-xs">
            {(slide.bullets ?? []).map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
          {slide.source && <p className="text-[0.65rem] text-(--ui-text-tertiary)">Source: {slide.source}</p>}
        </div>
      )}
      {slide?.notes && (
        <details className="text-xs">
          <summary className="cursor-pointer text-(--ui-text-tertiary)">Speaker notes</summary>
          <p className="mt-1 whitespace-pre-wrap">{slide.notes}</p>
        </details>
      )}
      <DownloadButton
        fallbackName="slides.pptx"
        label="Download PowerPoint"
        url={exportUrl(notebookId, artifact.id, 'pptx')}
      />
    </div>
  )
}
