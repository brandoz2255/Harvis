/** "Find sources" under an answer: runs the notebook's web search with the question and offers the pages to add. */

import { Button, Codicon, useQueryClient } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { blockedReason, useCapabilities } from './notebook-capabilities'
import { type FoundPage, searchWeb } from './notebook-discover-api'
import { PagePicker } from './notebook-page-picker'
import { errorText } from './notebook-shared'

export function FindSources({ notebookId, question }: { notebookId: string; question: string }) {
  const queryClient = useQueryClient()
  const blocked = blockedReason(useCapabilities()?.web_search)
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<FoundPage[] | null>(null)
  const [note, setNote] = useState('')

  if (question.trim().length < 2) {
    return null
  }

  const search = async () => {
    setBusy(true)
    setNote('')

    try {
      const found = await searchWeb(notebookId, question.trim())
      setResults(found.results)
      setNote(found.results.length === 0 ? found.message || 'No pages found for that question.' : '')
    } catch (err) {
      setResults(null)
      setNote(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button
        disabled={busy || !!blocked}
        onClick={() => void search()}
        size="xs"
        title={blocked || 'Search the web for pages that could answer this'}
        variant="ghost"
      >
        <Codicon name="search" size="0.8rem" /> {busy ? 'Searching…' : 'Find sources'}
      </Button>
      {note && <p className="basis-full text-xs text-(--ui-text-tertiary)">{note}</p>}
      {results && results.length > 0 && (
        <div className="basis-full">
          <PagePicker
            addLabel="Add as sources"
            notebookId={notebookId}
            onAdded={() => void queryClient.invalidateQueries({ queryKey: ['harvis', 'notebooks'] })}
            pages={results}
          />
        </div>
      )}
    </>
  )
}
