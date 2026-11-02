/**
 * Chat tab: ask the notebook, watch the answer being written, and get it grounded in its sources with
 * citations you can click through to the passage. Keep any answer as a note.
 */

import {
  Button,
  cn,
  Codicon,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { harvisApi } from './api'
import { ChatConfigButton } from './notebook-chat-config'
import { CitationList, CitedMarkdown, type OpenCitation, useCitationViewer } from './notebook-citation-link'
import { asCitations, citationLookup, type NotebookCitation, REFUSAL_TEXT } from './notebook-citations'
import { FindSources } from './notebook-find-sources'
import {
  isDefaultSelection,
  selectedSourceIds,
  summarySourceIds,
  takePendingQuestion,
  usePendingQuestion
} from './notebook-selection'
import {
  type ChatMessage,
  chatKey,
  createNote,
  errorText,
  listKey,
  notesKey,
  type Source,
  statsKey,
  useChosenModel
} from './notebook-shared'
import {
  type ContextReport,
  describeContext,
  parseDone,
  StreamUnavailable,
  type StreamedAnswer,
  streamNotebookChat
} from './notebook-stream'

type HistoryMessage = ChatMessage & { id?: string }

/** What the answer's own turn knew that the saved message may not (offsets, refusal, uncited). */
interface TurnInfo {
  citations: NotebookCitation[]
  context: ContextReport | null
  refused: boolean
  unsupported: boolean
}

const EMPTY_LOOKUP: ReadonlyMap<number, NotebookCitation> = new Map()
const MARKER = /\[\d{1,3}\]/

function SaveAnswer({
  citations,
  content,
  notebookId,
  question,
  unsupported
}: {
  citations: NotebookCitation[]
  content: string
  notebookId: string
  question: string
  unsupported: boolean
}) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<'error' | 'idle' | 'saved' | 'saving'>('idle')

  return (
    <Button
      disabled={state !== 'idle'}
      onClick={async () => {
        setState('saving')

        try {
          await createNote(notebookId, {
            content,
            source_meta: {
              citations,
              question,
              ...(unsupported ? { unsupported: true } : {})
            },
            title: question.slice(0, 120) || null,
            type: 'ai_note'
          })
          setState('saved')
          void queryClient.invalidateQueries({
            queryKey: notesKey(notebookId)
          })
          void queryClient.invalidateQueries({
            queryKey: statsKey(notebookId)
          })
          void queryClient.invalidateQueries({ queryKey: listKey })
        } catch {
          setState('error')
        }
      }}
      size="xs"
      variant="ghost"
    >
      {
        {
          error: 'Could not save',
          idle: 'Save as note',
          saved: 'Saved to notes',
          saving: 'Saving…'
        }[state]
      }
    </Button>
  )
}

/** Questions sit on the right in the same rounded bubble Hermes chat uses. */
const USER_BUBBLE =
  'ml-auto w-fit max-w-[85%] rounded-xl border border-(--dt-user-bubble-border) bg-(--dt-user-bubble) px-3 py-2 text-sm whitespace-pre-wrap'

function AnswerNotice({ refused }: { refused: boolean }) {
  return (
    <p className="mt-1.5 rounded-md bg-(--ui-bg-tertiary) px-2 py-1 text-xs text-(--ui-text-tertiary)">
      {refused
        ? 'Not found in your sources. No model was asked, so nothing here is made up.'
        : 'Not cited. No passage in your sources backs this answer, so treat it with care.'}
    </p>
  )
}

function Answer({
  info,
  message,
  notebookId,
  onOpen,
  question,
  showModel
}: {
  info?: TurnInfo
  message: HistoryMessage
  notebookId: string
  onOpen: OpenCitation
  question: string
  showModel: boolean
}) {
  const citations = info?.citations ?? asCitations(message.citations)
  const refused = info?.refused ?? message.content.trim() === REFUSAL_TEXT
  const unsupported = !refused && (info?.unsupported ?? (citations.length === 0 && !MARKER.test(message.content)))
  const lookup = refused || unsupported ? EMPTY_LOOKUP : citationLookup(citations)
  const contextNote = describeContext(info?.context ?? null)

  return (
    <>
      <div className={cn('prose prose-sm max-w-none dark:prose-invert', refused && 'text-(--ui-text-tertiary)')}>
        <CitedMarkdown citations={lookup} onOpen={onOpen} text={message.content} />
      </div>
      {(refused || unsupported) && <AnswerNotice refused={refused} />}
      {contextNote && <p className="mt-1.5 text-xs text-(--ui-text-tertiary)">{contextNote}</p>}
      {lookup.size > 0 && <CitationList citations={lookup} onOpen={onOpen} />}
      <div className="mt-1.5 -ml-2 flex flex-wrap items-center gap-x-1 text-(--ui-text-tertiary)">
        {!refused && (
          <SaveAnswer
            citations={citations}
            content={message.content}
            notebookId={notebookId}
            question={question}
            unsupported={unsupported}
          />
        )}
        <FindSources notebookId={notebookId} question={question} />
        {showModel && <span className="ml-auto text-xs">Answered by {message.model_used}</span>}
      </div>
    </>
  )
}

interface JsonChatReply {
  answer?: string
  citations?: unknown
  context?: unknown
  message_id?: string
  model_used?: string
  refused?: boolean
  unsupported?: boolean
}

const fromJson = (r: JsonChatReply): StreamedAnswer =>
  parseDone({ ...r, citations: Array.isArray(r.citations) ? r.citations : [] })

export function NotebookChat({
  intro,
  isOwner = false,
  notebookId,
  ready,
  sources
}: {
  /** Pinned above the messages; `ask` sends a question, `empty` is true before the first one. */
  intro?: (ask: (question: string) => void, empty: boolean) => ReactNode
  /** Only the owner may change how the notebook answers, so Configure chat shows for them alone. */
  isOwner?: boolean
  notebookId: string
  ready: boolean
  /** The notebook's sources; with it, sources set to Off in the Sources tab are left out of the answer. */
  sources?: readonly Source[]
}) {
  const queryClient = useQueryClient()
  const { available, choose, chosen, loading } = useChosenModel()
  const { open: openCitation, viewer } = useCitationViewer(notebookId)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<null | string>(null)
  const [streamed, setStreamed] = useState('')
  const [candidates, setCandidates] = useState<ReadonlyMap<number, NotebookCitation>>(EMPTY_LOOKUP)
  const [final, setFinal] = useState<null | StreamedAnswer>(null)
  const [turns, setTurns] = useState<ReadonlyMap<string, TurnInfo>>(new Map())
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const abort = useRef<AbortController | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const historyKey = chatKey(notebookId)

  // A suggested question picked on a source lands in the box, ready to send.
  const asked = usePendingQuestion(notebookId)

  useEffect(() => {
    if (asked) {
      const text = takePendingQuestion(notebookId)

      if (text) {
        setDraft(text)
      }
    }
  }, [asked, notebookId])

  const history = useQuery({
    queryFn: () =>
      harvisApi<{ messages: HistoryMessage[] }>(`/api/notebooks/${notebookId}/chat/history`).then(
        r => r.messages ?? []
      ),
    queryKey: historyKey
  })

  const ask = async (question?: string) => {
    const message = (question ?? draft).trim()

    if (!message || !chosen || pending) {
      return
    }

    // Sources set to Off stay out of the answer; with the default selection no list is sent (all sources).
    const sourceIds =
      sources && !isDefaultSelection(notebookId, sources) ? selectedSourceIds(notebookId, sources) : undefined

    if (sourceIds && sourceIds.length === 0) {
      setError('Every source is set to Off. Turn at least one on in the Sources tab.')

      return
    }

    // Sources at Summary are read as their stored summary: still in source_ids, and named again here.
    const summaryIds = sources ? summarySourceIds(notebookId, sources) : []

    const scope = {
      ...(sourceIds ? { source_ids: sourceIds } : {}),
      ...(summaryIds.length ? { summary_source_ids: summaryIds } : {})
    }

    const controller = new AbortController()

    abort.current = controller
    setPending(message)
    setDraft('')
    setError('')
    setNote('')
    setStreamed('')
    setCandidates(EMPTY_LOOKUP)
    setFinal(null)

    try {
      let answer: StreamedAnswer

      try {
        answer = await streamNotebookChat(
          notebookId,
          {
            message,
            model: chosen,
            ...scope
          },
          {
            onDelta: text => setStreamed(prev => prev + text),
            onSources: setCandidates
          },
          controller.signal
        )
      } catch (err) {
        if (controller.signal.aborted || !(err instanceof StreamUnavailable) || !err.retryable) {
          throw err
        }

        // Nothing was shown from the stream, so ask the plain route instead and wait for the whole answer.
        setStreamed('')
        answer = fromJson(
          await harvisApi<JsonChatReply>(`/api/notebooks/${notebookId}/chat`, {
            body: JSON.stringify({
              message,
              model: chosen,
              ...scope
            }),
            method: 'POST',
            signal: controller.signal
          })
        )
      }

      setStreamed(answer.answer)
      setFinal(answer)

      if (answer.messageId) {
        const id = answer.messageId

        setTurns(prev =>
          new Map(prev).set(id, {
            citations: answer.citations,
            context: answer.context,
            refused: answer.refused,
            unsupported: answer.unsupported
          })
        )
      }

      await queryClient.invalidateQueries({ queryKey: historyKey })
      void queryClient.invalidateQueries({ queryKey: statsKey(notebookId) })
    } catch (err) {
      setDraft(message)

      if (controller.signal.aborted) {
        setNote('Stopped. Nothing was saved.')
      } else {
        setError(errorText(err))
      }
    } finally {
      abort.current = null
      setPending(null)
    }
  }

  const messages = history.data ?? []
  const saved = !!final?.messageId && messages.some(m => m.id === final.messageId)
  const lookup = final ? citationLookup(final.citations) : candidates

  // Keep the newest turn in view as questions land and answers stream in.
  useEffect(() => {
    const el = scroller.current

    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages.length, pending, streamed])

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4" ref={scroller}>
        {intro?.(question => void ask(question), messages.length === 0 && !pending)}
        {history.isLoading ? (
          <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
        ) : history.error ? (
          <p className="text-xs text-destructive">{errorText(history.error)}</p>
        ) : null}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div className={USER_BUBBLE} key={m.id ?? i}>
              {m.content}
            </div>
          ) : (
            <div className="text-sm" key={m.id ?? i}>
              <Answer
                info={m.id ? turns.get(m.id) : undefined}
                message={m}
                notebookId={notebookId}
                onOpen={openCitation}
                question={messages[i - 1]?.role === 'user' ? messages[i - 1].content : ''}
                showModel={!!m.model_used && m.model_used !== chosen}
              />
            </div>
          )
        )}
        {pending && !saved && (
          <>
            <div className={USER_BUBBLE}>{pending}</div>
            {streamed ? (
              <div className="text-sm" data-testid="streaming-answer">
                <div className="prose prose-sm max-w-none dark:prose-invert">
                  <CitedMarkdown citations={lookup} onOpen={openCitation} streaming={!final} text={streamed} />
                </div>
                {final && lookup.size > 0 && <CitationList citations={lookup} onOpen={openCitation} />}
              </div>
            ) : (
              <p className="flex items-center gap-1.5 text-xs text-(--ui-text-tertiary)">
                <Codicon className="animate-spin" name="loading" size="0.8rem" /> Reading your sources and writing an
                answer…
              </p>
            )}
          </>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
        {note && <p className="text-xs text-(--ui-text-tertiary)">{note}</p>}
      </div>
      <form
        className="mx-3 mb-3 shrink-0 rounded-2xl border bg-(--ui-bg-editor) shadow-xs transition-colors focus-within:border-(--ui-stroke-secondary)"
        onSubmit={event => {
          event.preventDefault()

          void ask()
        }}
      >
        <Textarea
          className="max-h-40 min-h-11 resize-none border-0 bg-transparent px-3.5 pt-3 text-sm shadow-none focus-visible:ring-0 dark:bg-transparent"
          disabled={!ready}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()

              if (!pending && draft.trim() && chosen && ready) {
                void ask()
              }
            }
          }}
          placeholder={ready ? 'Ask something about these sources' : 'Add a source first'}
          rows={1}
          value={draft}
        />
        <div className="flex items-center gap-1 px-2 pb-2">
          {isOwner && <ChatConfigButton notebookId={notebookId} />}
          <Select onValueChange={choose} value={chosen ?? ''}>
            <SelectTrigger
              aria-label="Model"
              className="h-7 w-auto max-w-56 gap-1 border-0 bg-transparent px-2 text-xs text-(--ui-text-secondary) shadow-none hover:bg-(--ui-bg-tertiary) dark:bg-transparent"
            >
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
          <span className="flex-1" />
          {messages.length > 0 && !pending && (
            <Button
              aria-label="Delete chat history"
              onClick={async () => {
                if (!window.confirm("Delete this notebook's chat history?")) {
                  return
                }

                await harvisApi(`/api/notebooks/${notebookId}/chat/history`, {
                  method: 'DELETE'
                })
                void queryClient.invalidateQueries({ queryKey: historyKey })
              }}
              size="icon-xs"
              title="Delete this notebook's chat history"
              variant="ghost"
            >
              <Codicon name="trash" size="0.8rem" />
            </Button>
          )}
          {pending ? (
            <Button
              aria-label="Stop"
              className="size-7 rounded-full"
              onClick={() => abort.current?.abort()}
              size="icon"
              title="Stop"
              type="button"
              variant="outline"
            >
              <Codicon name="debug-stop" size="0.8rem" />
            </Button>
          ) : (
            <Button
              aria-label="Ask"
              className="size-7 rounded-full"
              disabled={!draft.trim() || !chosen || !ready}
              size="icon"
              title="Ask (Enter)"
              type="submit"
            >
              <Codicon name="arrow-up" size="0.85rem" />
            </Button>
          )}
        </div>
      </form>
      {viewer}
    </section>
  )
}
