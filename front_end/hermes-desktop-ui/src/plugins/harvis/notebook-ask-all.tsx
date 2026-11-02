/**
 * "Ask all notebooks": one question over every notebook you own. The server
 * (`POST /onb-api/search/ask`) plans a few searches, answers each from the
 * passages it finds, then writes one final answer. The passages come from a
 * separate vector search of the same question, because the ask stream itself
 * carries the answers but not the passages behind them.
 */

import {
  Button,
  Codicon,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Streamdown
} from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'

import { harvisApi } from './api'
import { errorText, readSse, type SseEvent, useChosenModel } from './notebook-shared'

export interface AskState {
  answers: string[]
  done: boolean
  error: string
  final: string
  reasoning: string
  searches: { instructions?: string; term: string }[]
}

export const EMPTY_ASK: AskState = { answers: [], done: false, error: '', final: '', reasoning: '', searches: [] }

const str = (v: unknown) => (typeof v === 'string' ? v : '')

/** Fold one event of the ask stream into the state. Unknown event types are ignored. */
export function applyAskEvent(state: AskState, { data }: SseEvent): AskState {
  switch (data.type) {
    case 'strategy':
      return {
        ...state,
        reasoning: str(data.reasoning),
        searches: (Array.isArray(data.searches) ? data.searches : [])
          .map(s => s as { instructions?: unknown; term?: unknown })
          .filter(s => str(s.term))
          .map(s => ({ instructions: str(s.instructions), term: str(s.term) }))
      }
    case 'answer':
      return { ...state, answers: [...state.answers, str(data.content)] }
    case 'final_answer':
      return { ...state, final: str(data.content) }
    case 'complete':
      return { ...state, done: true }
    case 'error':
      return { ...state, done: true, error: str(data.message) || 'The question failed.' }
    default:
      return state
  }
}

export interface Passage {
  snippet: string
  title: string
}

interface RawHit {
  matches?: unknown
  title?: unknown
}

export function toPassages(results: unknown): Passage[] {
  if (!Array.isArray(results)) {
    return []
  }

  return (results as RawHit[]).slice(0, 6).map(r => ({
    snippet: Array.isArray(r.matches) ? str(r.matches[0]).replace(/\s+/g, ' ').slice(0, 160) : '',
    title: str(r.title) || 'Untitled source'
  }))
}

function AskAllDialog({ onClose, open }: { onClose: () => void; open: boolean }) {
  const { chosen } = useChosenModel()
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [state, setState] = useState<AskState>(EMPTY_ASK)
  const [passages, setPassages] = useState<Passage[]>([])
  const abort = useRef<AbortController | null>(null)

  useEffect(() => () => abort.current?.abort(), [])

  const ask = async () => {
    const text = question.trim()

    if (!text || busy) {
      return
    }

    const controller = new AbortController()
    abort.current = controller
    setBusy(true)
    setState(EMPTY_ASK)
    setPassages([])

    // Best effort: the answer is useful without it.
    harvisApi<{ results: unknown }>('/onb-api/search', {
      body: JSON.stringify({ limit: 6, query: text, search_notes: false, type: 'vector' }),
      method: 'POST',
      signal: controller.signal
    })
      .then(r => setPassages(toPassages(r.results)))
      .catch(() => undefined)

    try {
      await readSse(
        '/onb-api/search/ask',
        {
          answer_model: chosen,
          final_answer_model: chosen,
          question: text,
          strategy_model: chosen
        },
        event => setState(prev => applyAskEvent(prev, event)),
        controller.signal
      )
    } catch (err) {
      if (!controller.signal.aborted) {
        setState(prev => ({ ...prev, done: true, error: errorText(err) }))
      }
    } finally {
      setBusy(false)
      abort.current = null
    }
  }

  const close = () => {
    abort.current?.abort()
    onClose()
  }

  return (
    <Dialog onOpenChange={next => !next && close()} open={open}>
      <DialogContent bodyClassName="flex max-h-[80vh] flex-col gap-3 p-4" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Ask all notebooks</DialogTitle>
          <DialogDescription>One question over everything in all of your notebooks.</DialogDescription>
        </DialogHeader>
        <form
          className="flex gap-1.5"
          onSubmit={event => {
            event.preventDefault()
            void ask()
          }}
        >
          <Input
            aria-label="Your question"
            autoFocus
            className="min-w-0 flex-1"
            onChange={e => setQuestion(e.target.value)}
            placeholder="What do my notebooks say about…"
            value={question}
          />
          {busy ? (
            <Button onClick={() => abort.current?.abort()} size="sm" type="button" variant="outline">
              Stop
            </Button>
          ) : (
            <Button disabled={!question.trim()} size="sm" type="submit">
              Ask
            </Button>
          )}
        </form>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto text-sm">
          {busy && !state.reasoning && !state.final && (
            <p className="text-xs text-(--ui-text-tertiary)">
              <Codicon name="loading" size="0.8rem" spinning /> Planning the searches…
            </p>
          )}
          {state.searches.length > 0 && (
            <div className="space-y-1 text-xs text-(--ui-text-tertiary)">
              {state.reasoning && <p>{state.reasoning}</p>}
              <ul className="list-disc pl-4">
                {state.searches.map(s => (
                  <li key={s.term}>{s.term}</li>
                ))}
              </ul>
              {busy && !state.final && (
                <p>
                  <Codicon name="loading" size="0.8rem" spinning /> {state.answers.length} of {state.searches.length}{' '}
                  searches answered…
                </p>
              )}
            </div>
          )}
          {state.final && (
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <Streamdown mode="static">{state.final}</Streamdown>
            </div>
          )}
          {state.error && <p className="text-xs text-destructive">{state.error}</p>}
          {passages.length > 0 && (
            <div className="space-y-1 border-t pt-2">
              <p className="text-[0.65rem] tracking-wide text-(--ui-text-tertiary) uppercase">Passages found</p>
              <ol className="space-y-1">
                {passages.map((p, i) => (
                  <li className="text-xs" key={i}>
                    <span className="font-medium">{p.title}</span>
                    {p.snippet && <span className="text-(--ui-text-tertiary)"> — {p.snippet}</span>}
                  </li>
                ))}
              </ol>
            </div>
          )}
          {state.answers.length > 1 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-(--ui-text-tertiary)">Answers to each search</summary>
              <div className="mt-1 space-y-2">
                {state.answers.map((a, i) => (
                  <div className="prose prose-sm max-w-none text-xs dark:prose-invert" key={i}>
                    <Streamdown mode="static">{a}</Streamdown>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function AskAllButton({ variant = 'ghost' }: { variant?: 'ghost' | 'outline' }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button onClick={() => setOpen(true)} size="sm" variant={variant}>
        <Codicon name="search" size="0.8rem" /> Ask all notebooks
      </Button>
      {open && <AskAllDialog onClose={() => setOpen(false)} open />}
    </>
  )
}
