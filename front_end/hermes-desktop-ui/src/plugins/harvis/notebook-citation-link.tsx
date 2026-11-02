/**
 * Clickable citations: `[n]` markers inside a rendered answer, the list under it, and the source viewer
 * they open. Hovering a marker shows the passage; clicking opens the source scrolled to it.
 */

import { Streamdown, Tip } from '@hermes/plugin-sdk'
import { type ComponentProps, type ReactNode, useCallback, useMemo, useState } from 'react'

import {
  CITE_SCHEME,
  citationLabel,
  citationPassage,
  hidePartialMarker,
  linkCitations,
  type NotebookCitation,
  normalizeCitationMarkers
} from './notebook-citations'
import type { Source } from './notebook-shared'
import { NotebookSourceViewer } from './notebook-source-viewer'

export type OpenCitation = (citation: NotebookCitation) => void

const TIP_CHARS = 240

export function CitationChip({ citation, n, onOpen }: { citation: NotebookCitation; n: number; onOpen: OpenCitation }) {
  const passage = citationPassage(citation)

  if (!citation.source_id) {
    return <span className="text-[0.72em] text-(--ui-text-tertiary)">[{n}]</span>
  }

  return (
    <Tip
      label={
        <span>
          {citationLabel(citation)}
          {passage && <span className="block font-normal italic">“{passage.slice(0, TIP_CHARS)}”</span>}
        </span>
      }
    >
      <button
        aria-label={`Source ${n}: ${citationLabel(citation)}`}
        className="mx-px cursor-pointer rounded bg-primary/10 px-1 align-baseline text-[0.72em] font-medium text-primary hover:bg-primary/20"
        data-citation={n}
        onClick={() => onOpen(citation)}
        type="button"
      >
        [{n}]
      </button>
    </Tip>
  )
}

/** An answer with its `[n]` markers as buttons; `citations` maps each marker number to its passage. */
export function CitedMarkdown({
  citations,
  onOpen,
  streaming = false,
  text
}: {
  citations: ReadonlyMap<number, NotebookCitation>
  onOpen: OpenCitation
  streaming?: boolean
  text: string
}) {
  const components = useMemo(
    () => ({
      a: ({ children, href, node: _node, ...rest }: ComponentProps<'a'> & { node?: unknown }): ReactNode => {
        if (href?.startsWith(CITE_SCHEME)) {
          const n = Number(href.slice(CITE_SCHEME.length))
          const citation = citations.get(n)

          return citation ? <CitationChip citation={citation} n={n} onOpen={onOpen} /> : <>{children}</>
        }

        return href && /^https?:\/\//i.test(href) ? (
          <a {...rest} href={href} rel="noopener noreferrer" target="_blank">
            {children}
          </a>
        ) : (
          <>{children}</>
        )
      }
    }),
    [citations, onOpen]
  )

  const known = useMemo(() => new Set(citations.keys()), [citations])
  const markdown = linkCitations(normalizeCitationMarkers(streaming ? hidePartialMarker(text) : text), known)

  return (
    <Streamdown components={components} mode={streaming ? 'streaming' : 'static'}>
      {markdown}
    </Streamdown>
  )
}

/** The sources under an answer, in marker order; each opens its passage. */
export function CitationList({
  citations,
  onOpen
}: {
  citations: ReadonlyMap<number, NotebookCitation>
  onOpen: OpenCitation
}) {
  return (
    <ol className="mt-1.5 space-y-1 text-xs text-(--ui-text-tertiary)">
      {[...citations].map(([n, c]) => {
        const passage = citationPassage(c)

        const body = (
          <>
            [{n}] {citationLabel(c)}
            {passage && <span className="block italic">“{passage.slice(0, 220)}”</span>}
          </>
        )

        return (
          <li key={n}>
            {c.source_id ? (
              <button
                className="w-full cursor-pointer text-left hover:text-foreground hover:underline"
                onClick={() => onOpen(c)}
                title="Open this passage in its source"
                type="button"
              >
                {body}
              </button>
            ) : (
              body
            )}
          </li>
        )
      })}
    </ol>
  )
}

const asSource = (c: NotebookCitation): Source => ({
  chunk_count: null,
  error_message: null,
  id: c.source_id ?? '',
  original_filename: null,
  status: 'ready',
  title: c.source_title ?? null,
  type: ''
})

/** One source viewer for a whole tab: `open(citation)` shows it, `viewer` goes anywhere in the tree. */
export function useCitationViewer(notebookId: string): { open: OpenCitation; viewer: ReactNode } {
  const [cited, setCited] = useState<NotebookCitation | null>(null)
  const open = useCallback<OpenCitation>(c => setCited(c), [])

  const viewer = (
    <NotebookSourceViewer
      notebookId={notebookId}
      onClose={() => setCited(null)}
      source={cited?.source_id ? asSource(cited) : null}
      target={cited}
    />
  )

  return { open, viewer }
}
