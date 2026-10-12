/**
 * Review one generated artifact in the Studio rail: a quiz you can take, a deck
 * of flashcards you can flip, or a Markdown report you can keep as a note.
 */

import { Button, Codicon, Streamdown, useQueryClient } from '@hermes/plugin-sdk'
import { useState } from 'react'

import type { Artifact } from './notebook-artifacts'
import { Flashcards } from './notebook-flashcards'
import { MindMap } from './notebook-mindmap'
import { Quiz } from './notebook-quiz'
import { createNote, listKey, notesKey, statsKey } from './notebook-shared'

function KeepReport({ artifact, notebookId }: { artifact: Artifact; notebookId: string }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<'error' | 'idle' | 'saved' | 'saving'>('idle')

  return (
    <Button
      disabled={state !== 'idle'}
      onClick={async () => {
        setState('saving')

        try {
          await createNote(notebookId, {
            content: artifact.content?.markdown ?? '',
            title: artifact.title,
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

export function ArtifactView({
  artifact,
  notebookId,
  onBack
}: {
  artifact: Artifact
  notebookId: string
  onBack: () => void
}) {
  const content = artifact.content ?? {}

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        <Button aria-label="Back to Studio" onClick={onBack} size="xs" variant="ghost">
          <Codicon name="arrow-left" size="0.8rem" />
        </Button>
        <h4 className="min-w-0 flex-1 truncate text-sm font-semibold">{artifact.title}</h4>
      </div>
      {content.questions?.length ? (
        <Quiz questions={content.questions} />
      ) : content.cards?.length ? (
        <Flashcards cards={content.cards} />
      ) : content.tree?.children?.length ? (
        <MindMap tree={content.tree} />
      ) : content.markdown ? (
        <>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Streamdown mode="static">{content.markdown}</Streamdown>
          </div>
          <KeepReport artifact={artifact} notebookId={notebookId} />
        </>
      ) : (
        <p className="text-xs text-(--ui-text-tertiary)">This item has nothing to show.</p>
      )}
    </div>
  )
}
