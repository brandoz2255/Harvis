/**
 * Discover: find material on the web and add it to the notebook without leaving
 * it. Fast research is one web search whose results you tick and add as web page
 * sources. Deep research runs the multi-round research job, then adds its report
 * as a source and offers the pages it cited. Pages are read by the server's
 * public-web-only fetcher, so private addresses are refused there.
 */

import { Button, cn, Codicon, Input } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { blockedReason, useCapabilities } from './notebook-capabilities'
import { type FoundPage, searchWeb } from './notebook-discover-api'
import { DeepResearch } from './notebook-discover-deep'
import { PagePicker } from './notebook-page-picker'
import { errorText } from './notebook-shared'

function FastResearch({ notebookId, onAdded }: { notebookId: string; onAdded: () => void }) {
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<FoundPage[] | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const caps = useCapabilities()
  const blocked = blockedReason(caps?.web_search)

  const search = async () => {
    setBusy(true)
    setError('')
    setMessage('')

    try {
      const found = await searchWeb(notebookId, query.trim())
      setResults(found.results)
      setMessage(found.results.length === 0 ? found.message || 'No results. Try different words.' : '')
    } catch (err) {
      setResults(null)
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <form
        className="flex gap-1.5"
        onSubmit={event => {
          event.preventDefault()
          void search()
        }}
      >
        <Input
          aria-label="Search the web"
          className="min-w-0 flex-1"
          disabled={!!blocked}
          onChange={e => setQuery(e.target.value)}
          placeholder="What do you want to learn about?"
          value={query}
        />
        <Button disabled={query.trim().length < 2 || busy || !!blocked} size="sm" type="submit">
          {busy ? 'Searching…' : 'Search'}
        </Button>
      </form>
      {blocked && <p className="text-xs text-destructive">{blocked}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
      {message && <p className="text-xs text-(--ui-text-tertiary)">{message}</p>}
      {results && results.length > 0 && (
        <PagePicker addLabel="Add as sources" notebookId={notebookId} onAdded={onAdded} pages={results} />
      )}
    </div>
  )
}

export function NotebookDiscover({ notebookId, onAdded }: { notebookId: string; onAdded: () => void }) {
  const [mode, setMode] = useState<'deep' | 'fast'>('fast')

  return (
    <div className="space-y-2">
      <div className="flex gap-1 text-xs">
        {(['fast', 'deep'] as const).map(m => (
          <button
            className={cn(
              'flex items-center gap-1 rounded px-2 py-0.5',
              mode === m ? 'bg-(--ui-bg-tertiary) text-foreground' : 'text-(--ui-text-tertiary) hover:text-foreground'
            )}
            key={m}
            onClick={() => setMode(m)}
            type="button"
          >
            <Codicon name={m === 'fast' ? 'search' : 'telescope'} size="0.75rem" />
            {m === 'fast' ? 'Fast research' : 'Deep research'}
          </button>
        ))}
      </div>
      <p className="text-xs text-(--ui-text-tertiary)">
        {mode === 'fast'
          ? 'Search the web, tick the pages you want, and add them as sources.'
          : 'Reads many pages over a few minutes and writes a cited report you can add as a source.'}
      </p>
      {mode === 'fast' ? (
        <FastResearch notebookId={notebookId} onAdded={onAdded} />
      ) : (
        <DeepResearch notebookId={notebookId} onAdded={onAdded} />
      )}
    </div>
  )
}
