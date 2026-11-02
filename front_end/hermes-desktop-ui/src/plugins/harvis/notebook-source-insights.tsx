/**
 * What Harvis wrote about a source when it was added: a dense summary and a few
 * questions worth asking. Mount it wherever a source is shown. Pass `onAsk` to
 * make the questions clickable.
 */

import { Button, cn, Codicon, Streamdown, useQuery, useQueryClient } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { harvisApi } from './api'
import { insightsState, suggestedQuestions } from './notebook-source-meta'
import { createNote, errorText, listKey, notesKey, type Source, sourceLabel, statsKey } from './notebook-shared'

interface Insight {
  content: string
  id: string
  insight_type: string
}

export const insightsKey = (sourceId: string) => ['harvis', 'notebooks', 'source-insights', sourceId] as const

/** The auto-written summary: the row the backend named, else the newest plain summary. */
export function pickSummary(insights: readonly Insight[], summaryId?: null | string): Insight | undefined {
  return (
    insights.find(i => i.id === summaryId) ??
    (summaryId ? undefined : insights.find(i => i.insight_type === 'summarize'))
  )
}

function SaveSummary({ notebookId, source, text }: { notebookId: string; source: Source; text: string }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<'error' | 'idle' | 'saved' | 'saving'>('idle')

  const save = async () => {
    setState('saving')

    try {
      await createNote(notebookId, { content: text, title: `Summary: ${sourceLabel(source)}`, type: 'ai_note' })
      setState('saved')
      void queryClient.invalidateQueries({ queryKey: notesKey(notebookId) })
      void queryClient.invalidateQueries({ queryKey: statsKey(notebookId) })
      void queryClient.invalidateQueries({ queryKey: listKey })
    } catch {
      setState('error')
    }
  }

  return (
    <Button disabled={state !== 'idle'} onClick={() => void save()} size="xs" variant="ghost">
      {{ error: 'Could not save', idle: 'Save as note', saved: 'Saved to notes', saving: 'Saving…' }[state]}
    </Button>
  )
}

export function NotebookSourceInsights({
  className,
  notebookId,
  onAsk,
  source
}: {
  className?: string
  notebookId: string
  onAsk?: (question: string) => void
  source: Source
}) {
  const state = insightsState(source)
  const questions = suggestedQuestions(source)

  const insights = useQuery({
    enabled: state === 'done',
    queryFn: () => harvisApi<Insight[]>(`/onb-api/sources/${encodeURIComponent(source.id)}/insights`),
    queryKey: insightsKey(source.id),
    staleTime: 5 * 60_000
  })

  if (state === 'none') {
    return null
  }

  const summary = pickSummary(insights.data ?? [], source.metadata?.summary_insight_id)

  return (
    <div className={cn('space-y-2 rounded-md bg-(--ui-bg-tertiary) p-3 text-xs', className)}>
      {state === 'pending' && (
        <p className="flex items-center gap-1.5 text-(--ui-text-tertiary)">
          <Codicon name="loading" size="0.8rem" spinning /> Writing a summary…
        </p>
      )}
      {state === 'error' && (
        <p className="text-destructive">
          No summary: {source.metadata?.insights_error || 'writing it failed.'} The source itself is fine.
        </p>
      )}
      {state === 'done' && insights.isLoading && <p className="text-(--ui-text-tertiary)">Loading summary…</p>}
      {insights.error && <p className="text-destructive">{errorText(insights.error)}</p>}
      {summary && (
        <div>
          <div className="flex items-center gap-2">
            <span className="flex-1 font-medium">Summary</span>
            <SaveSummary notebookId={notebookId} source={source} text={summary.content} />
          </div>
          <div className="prose prose-sm max-w-none text-xs dark:prose-invert">
            <Streamdown mode="static">{summary.content}</Streamdown>
          </div>
        </div>
      )}
      {questions.length > 0 && (
        <div>
          <p className="mb-1 font-medium">Questions to ask</p>
          <ul className="space-y-1">
            {questions.map(q => (
              <li key={q}>
                {onAsk ? (
                  <button
                    className="text-left text-(--ui-text-secondary) underline-offset-2 hover:text-foreground hover:underline"
                    onClick={() => onAsk(q)}
                    type="button"
                  >
                    {q}
                  </button>
                ) : (
                  <span className="text-(--ui-text-secondary)">{q}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
