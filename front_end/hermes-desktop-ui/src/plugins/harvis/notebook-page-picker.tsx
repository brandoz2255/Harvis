/** A list of found pages with a tick box each and one button that adds the ticked ones as web page sources. */

import { Button } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { addPages, addSummary, type FoundPage } from './notebook-discover-api'
import { errorText } from './notebook-shared'

export function PagePicker({
  addLabel = 'Add selected',
  notebookId,
  onAdded,
  pages
}: {
  addLabel?: string
  notebookId: string
  onAdded: () => void
  pages: FoundPage[]
}) {
  const [ticked, setTicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  const toggle = (url: string) =>
    setTicked(prev => {
      const next = new Set(prev)

      if (!next.delete(url)) {
        next.add(url)
      }

      return next
    })

  const add = async () => {
    setBusy(true)
    setError('')
    setNote('')

    try {
      const result = await addPages(
        notebookId,
        pages.filter(p => ticked.has(p.url))
      )
      setNote(addSummary(result))
      setTicked(new Set())
      onAdded()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-1.5">
      <ul className="divide-y rounded-lg border">
        {pages.map(p => (
          <li key={p.url}>
            <label className="flex cursor-pointer items-start gap-2 px-3 py-2 text-sm hover:bg-(--ui-bg-secondary)">
              <input
                aria-label={`Select ${p.title}`}
                checked={ticked.has(p.url)}
                className="mt-1"
                onChange={() => toggle(p.url)}
                type="checkbox"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{p.title}</span>
                <span className="block truncate text-xs text-(--ui-text-tertiary)">{p.site}</span>
                {p.snippet && <span className="mt-0.5 line-clamp-2 block text-xs">{p.snippet}</span>}
              </span>
            </label>
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-2">
        <Button disabled={ticked.size === 0 || busy} onClick={() => void add()} size="sm">
          {busy ? 'Adding…' : `${addLabel}${ticked.size > 0 ? ` (${ticked.size})` : ''}`}
        </Button>
        <Button
          disabled={busy}
          onClick={() => setTicked(ticked.size === pages.length ? new Set() : new Set(pages.map(p => p.url)))}
          size="sm"
          variant="ghost"
        >
          {ticked.size === pages.length ? 'Clear' : 'Select all'}
        </Button>
      </div>
      {note && <p className="text-xs text-(--ui-text-tertiary)">{note}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
