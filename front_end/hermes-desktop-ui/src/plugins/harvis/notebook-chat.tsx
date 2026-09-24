/**
 * Chat tab: ask the notebook, get an answer grounded in its sources with
 * citations back to the passage used, and keep any answer as a note.
 */

import {
  Button,
  cn,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Streamdown,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useState } from 'react'

import { harvisApi } from './api'
import {
  type ChatMessage,
  chatKey,
  createNote,
  errorText,
  listKey,
  notesKey,
  statsKey,
  useChosenModel
} from './notebook-shared'

function SaveAnswer({ message, notebookId, question }: { message: ChatMessage; notebookId: string; question: string }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<'error' | 'idle' | 'saved' | 'saving'>('idle')

  return (
    <Button
      disabled={state !== 'idle'}
      onClick={async () => {
        setState('saving')

        try {
          await createNote(notebookId, {
            content: message.content,
            source_meta: { citations: message.citations ?? [], question },
            title: question.slice(0, 120) || null,
            type: 'ai_note'
          })
          setState('saved')
          void queryClient.invalidateQueries({ queryKey: notesKey(notebookId) })
          void queryClient.invalidateQueries({ queryKey: statsKey(notebookId) })
          void queryClient.invalidateQueries({ queryKey: listKey })
        } catch {
          setState('error')
        }
      }}
      size="xs"
      variant="ghost"
    >
      {{ error: 'Could not save', idle: 'Save as note', saved: 'Saved to notes', saving: 'Saving…' }[state]}
    </Button>
  )
}

export function NotebookChat({ notebookId, ready }: { notebookId: string; ready: boolean }) {
  const queryClient = useQueryClient()
  const { available, choose, chosen, loading } = useChosenModel()
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<null | string>(null)
  const [error, setError] = useState('')
  const historyKey = chatKey(notebookId)

  const history = useQuery({
    queryFn: () =>
      harvisApi<{ messages: ChatMessage[] }>(`/api/notebooks/${notebookId}/chat/history`).then(r => r.messages ?? []),
    queryKey: historyKey
  })

  const ask = async () => {
    const message = draft.trim()
    setPending(message)
    setDraft('')
    setError('')

    try {
      await harvisApi(`/api/notebooks/${notebookId}/chat`, {
        method: 'POST',
        body: JSON.stringify({ message, model: chosen, top_k: 5 })
      })
      await queryClient.invalidateQueries({ queryKey: historyKey })
      void queryClient.invalidateQueries({ queryKey: statsKey(notebookId) })
    } catch (err) {
      setError(errorText(err))
      setDraft(message)
    } finally {
      setPending(null)
    }
  }

  const messages = history.data ?? []

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="flex-1 text-sm font-medium">Ask your sources</h3>
        <Select onValueChange={choose} value={chosen ?? ''}>
          <SelectTrigger className="h-7 w-52 text-xs">
            <SelectValue placeholder={loading ? 'Loading models…' : 'No models online'} />
          </SelectTrigger>
          <SelectContent>
            {available.map(m => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {messages.length > 0 && (
          <Button
            onClick={async () => {
              await harvisApi(`/api/notebooks/${notebookId}/chat/history`, { method: 'DELETE' })
              void queryClient.invalidateQueries({ queryKey: historyKey })
            }}
            size="sm"
            variant="ghost"
          >
            Clear
          </Button>
        )}
      </div>
      {history.isLoading ? (
        <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
      ) : history.error ? (
        <p className="text-xs text-destructive">{errorText(history.error)}</p>
      ) : null}
      <div className="space-y-3">
        {messages.map((m, i) => (
          <div className={cn('text-sm', m.role === 'user' && 'rounded-lg bg-(--ui-bg-tertiary) px-3 py-2')} key={i}>
            {m.role === 'user' ? (
              m.content
            ) : (
              <>
                <div className="prose prose-sm max-w-none dark:prose-invert">
                  <Streamdown mode="static">{m.content.replace(/【\s*SOURCE\s*(\d+)\s*】/gi, ' [$1]')}</Streamdown>
                </div>
                {m.citations?.length > 0 && (
                  <ol className="mt-1.5 space-y-1 text-xs text-(--ui-text-tertiary)">
                    {m.citations.map((c, j) => (
                      <li key={j}>
                        [{j + 1}] {c.source_title || 'Source'}
                        {c.page ? `, page ${c.page}` : ''}
                        {c.quote && <span className="block italic">“{c.quote.slice(0, 220)}”</span>}
                      </li>
                    ))}
                  </ol>
                )}
                <div className="mt-1">
                  <SaveAnswer
                    message={m}
                    notebookId={notebookId}
                    question={messages[i - 1]?.role === 'user' ? messages[i - 1].content : ''}
                  />
                </div>
              </>
            )}
          </div>
        ))}
        {pending && (
          <>
            <div className="rounded-lg bg-(--ui-bg-tertiary) px-3 py-2 text-sm">{pending}</div>
            <p className="text-xs text-(--ui-text-tertiary)">Reading your sources and writing an answer…</p>
          </>
        )}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <form
        className="flex gap-1.5"
        onSubmit={event => {
          event.preventDefault()

          if (draft.trim() && chosen && !pending) {
            void ask()
          }
        }}
      >
        <Input
          className="min-w-0 flex-1"
          disabled={!ready}
          onChange={e => setDraft(e.target.value)}
          placeholder={ready ? 'Ask something about these sources' : 'Add a source first'}
          value={draft}
        />
        <Button disabled={!draft.trim() || !chosen || !!pending || !ready} size="sm" type="submit">
          Ask
        </Button>
      </form>
    </section>
  )
}
