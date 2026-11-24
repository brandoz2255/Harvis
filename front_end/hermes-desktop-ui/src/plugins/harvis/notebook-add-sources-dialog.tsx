/**
 * The "Add sources" prompt, NotebookLM style: it opens by itself on a notebook
 * with no sources (and from the header button), and asks for the three ways in:
 * drop files, search the web, or run deep research. A link or pasted text is one
 * click further. Every path reuses the Sources tab's own pieces and endpoints.
 */

import {
  Button,
  cn,
  Codicon,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useState } from 'react'

import { AddSource, SourceIndexNotice } from './notebook-add-source'
import { FastResearch } from './notebook-discover'
import { DeepResearch } from './notebook-discover-deep'
import type { Source } from './notebook-shared'
import { SourceDropZone } from './notebook-source-drop'

type View = 'deep' | 'fast' | 'home' | 'text' | 'url'

const WAYS: { blurb: string; icon: string; label: string; view: 'deep' | 'fast' }[] = [
  { blurb: 'One search; tick the pages you want.', icon: 'search', label: 'Search the web', view: 'fast' },
  { blurb: 'A few minutes; writes a cited report.', icon: 'telescope', label: 'Deep research', view: 'deep' }
]

const TITLES: Record<Exclude<View, 'home'>, string> = {
  deep: 'Deep research',
  fast: 'Search the web',
  text: 'Paste text',
  url: 'Web page or YouTube link'
}

export function AddSourcesDialog({
  notebookId,
  onOpenChange,
  open,
  sources
}: {
  notebookId: string
  onOpenChange: (open: boolean) => void
  open: boolean
  sources: readonly Source[]
}) {
  const queryClient = useQueryClient()
  const [view, setView] = useState<View>('home')
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['harvis', 'notebooks'] })

  const close = (next: boolean) => {
    onOpenChange(next)

    if (!next) {
      setView('home')
    }
  }

  return (
    <Dialog onOpenChange={close} open={open}>
      <DialogContent bodyClassName="flex max-h-[85vh] flex-col gap-4 overflow-y-auto p-5" className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{view === 'home' ? 'Add sources' : TITLES[view]}</DialogTitle>
          <DialogDescription>
            {view === 'home'
              ? 'This notebook answers from its sources. Drop in your own files, or let Harvis find some on the web.'
              : 'Added sources show up in the Sources panel as soon as they are read.'}
          </DialogDescription>
        </DialogHeader>
        {view !== 'home' && (
          <button
            className="flex items-center gap-1 self-start text-xs text-(--ui-text-tertiary) hover:text-foreground"
            onClick={() => setView('home')}
            type="button"
          >
            <Codicon name="arrow-left" size="0.75rem" /> All the ways to add sources
          </button>
        )}
        {view === 'home' && (
          <>
            <SourceIndexNotice notebookId={notebookId} sources={sources} />
            <SourceDropZone
              notebookId={notebookId}
              onAdded={clean => {
                refresh()

                if (clean) {
                  close(false)
                }
              }}
            />
            <div className="grid grid-cols-2 gap-2">
              {WAYS.map(w => (
                <button
                  className={cn(
                    'flex flex-col items-start gap-0.5 rounded-xl border px-3 py-2.5 text-left transition-colors',
                    'hover:bg-(--ui-bg-tertiary)'
                  )}
                  key={w.view}
                  onClick={() => setView(w.view)}
                  type="button"
                >
                  <span className="flex items-center gap-1.5 text-sm font-medium">
                    <Codicon name={w.icon} size="0.85rem" /> {w.label}
                  </span>
                  <span className="text-xs text-(--ui-text-tertiary)">{w.blurb}</span>
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1.5 text-xs text-(--ui-text-tertiary)">
              <span>Or add</span>
              <Button onClick={() => setView('url')} size="xs" variant="outline">
                <Codicon name="link" size="0.75rem" /> a link
              </Button>
              <Button onClick={() => setView('text')} size="xs" variant="outline">
                <Codicon name="note" size="0.75rem" /> pasted text
              </Button>
            </div>
          </>
        )}
        {view === 'fast' && <FastResearch notebookId={notebookId} onAdded={refresh} />}
        {view === 'deep' && <DeepResearch notebookId={notebookId} onAdded={refresh} />}
        {(view === 'url' || view === 'text') && (
          <AddSource
            initialKind={view}
            notebookId={notebookId}
            onAdded={() => {
              refresh()
              close(false)
            }}
            sources={sources}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
