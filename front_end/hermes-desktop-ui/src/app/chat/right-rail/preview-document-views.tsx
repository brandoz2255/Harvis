import { type ComponentProps, type ElementType, type FC, memo, useEffect, useMemo, useRef, useState } from 'react'
import { Streamdown } from 'streamdown'

import { useI18n } from '@/i18n'
import { ExternalLink } from '@/lib/external-link'
import type { HarvisDoc } from '@/lib/harvis-doc'
import { cn } from '@/lib/utils'

import {
  DocCheckbox,
  DocFenceContext,
  docMathPlugin,
  DocPre,
  normalizeDocMath,
  openFenceLine,
  StatusText
} from './doc-blocks'
import { type DocPart, splitNotes } from './preview-document-parts'

const PULSE = 'animate-pulse motion-reduce:animate-none'

// Sizes are em-based so one component map serves a slide (font-size in cqw), a
// document column (text-sm) and a PDF page. Colours inherit from the surface,
// which lets the PDF page stay white paper in a dark theme.
const TAGS = {
  blockquote: 'mb-[0.7em] border-l-2 border-current/25 pl-[0.8em] italic opacity-80 last:mb-0',
  h1: 'mb-[0.5em] mt-[0.9em] text-[1.6em] font-bold leading-tight tracking-tight first:mt-0',
  h2: 'mb-[0.45em] mt-[0.9em] text-[1.3em] font-semibold leading-snug tracking-tight first:mt-0',
  h3: 'mb-[0.4em] mt-[0.8em] text-[1.12em] font-semibold leading-snug first:mt-0',
  h4: 'mb-[0.35em] mt-[0.7em] font-semibold leading-snug first:mt-0',
  hr: 'my-[1em] border-current/20',
  li: 'mt-[0.25em] leading-relaxed marker:opacity-60',
  ol: 'mb-[0.7em] list-decimal pl-[1.5em] last:mb-0',
  p: 'mb-[0.7em] leading-relaxed last:mb-0',
  pre: 'mb-[0.7em] overflow-x-auto rounded-md border border-current/15 bg-current/5 p-[0.7em] font-mono text-[0.85em] leading-relaxed last:mb-0',
  td: 'border-t border-current/15 px-[0.7em] py-[0.4em] align-top leading-snug',
  th: 'px-[0.7em] py-[0.4em] text-left text-[0.85em] font-semibold',
  thead: 'bg-current/5',
  ul: 'mb-[0.7em] list-disc pl-[1.5em] last:mb-0'
} as const

function tagged<T extends keyof typeof TAGS>(Tag: T) {
  const Component = (({ className, node: _node, ...rest }: ComponentProps<T> & { node?: unknown }) => {
    const Element = Tag as ElementType

    return <Element className={cn(TAGS[Tag], className)} {...rest} />
  }) as FC<ComponentProps<T>>

  Component.displayName = `DocMd.${Tag}`

  return Component
}

function DocAnchor({ children, className, href, node: _node, ...rest }: ComponentProps<'a'> & { node?: unknown }) {
  if (!href || !/^https?:\/\//i.test(href)) {
    return (
      <a className={cn('underline underline-offset-2', className)} href={href} {...rest}>
        {children}
      </a>
    )
  }

  return (
    <ExternalLink className={cn('underline underline-offset-2', className)} href={href}>
      {children}
    </ExternalLink>
  )
}

// `- [ ]` items arrive as `<ul class="contains-task-list">`; the checkbox stands in for the bullet.
function taggedList<T extends 'ol' | 'ul'>(Tag: T) {
  const List = tagged(Tag) as FC<ComponentProps<'ul'>>
  const Component: FC<ComponentProps<'ul'>> = ({ className, ...rest }) => (
    <List className={cn(className?.includes('contains-task-list') && 'list-none pl-0', className)} {...rest} />
  )

  Component.displayName = `DocMd.${Tag}.list`

  return Component
}

const DocTd = tagged('td')

function DocCell({ children, ...rest }: ComponentProps<'td'>) {
  return (
    <DocTd {...rest}>
      <StatusText>{children}</StatusText>
    </DocTd>
  )
}

const MARKDOWN_COMPONENTS = {
  a: DocAnchor,
  blockquote: tagged('blockquote'),
  code: ({ className, node: _node, ...rest }: ComponentProps<'code'> & { node?: unknown }) => (
    <code className={cn('rounded bg-current/10 px-1 py-px font-mono text-[0.88em]', className)} {...rest} />
  ),
  h1: tagged('h1'),
  h2: tagged('h2'),
  h3: tagged('h3'),
  h4: tagged('h4'),
  hr: tagged('hr'),
  // A model-written image URL would be fetched the moment it streams in.
  img: ({ alt }: ComponentProps<'img'>) => <span className="opacity-60">[{alt || 'image'}]</span>,
  input: DocCheckbox,
  li: tagged('li'),
  ol: taggedList('ol'),
  p: tagged('p'),
  pre: DocPre,
  table: ({ className, node: _node, ...rest }: ComponentProps<'table'> & { node?: unknown }) => (
    <div className="mb-[0.7em] max-w-full overflow-x-auto rounded-md border border-current/15 last:mb-0">
      <table className={cn('w-full border-collapse text-[0.9em]', className)} {...rest} />
    </div>
  ),
  td: DocCell,
  th: tagged('th'),
  thead: tagged('thead'),
  ul: taggedList('ul')
}

const PLUGINS = { math: docMathPlugin }

/** The text caret that marks where the model is writing, with a small name tag above it. One per document. */
export function WritingCaret() {
  const { t } = useI18n()

  return (
    <span aria-hidden className="relative ml-px inline-block align-baseline" data-slot="doc-caret">
      <span
        className="absolute bottom-[1.05em] left-0 select-none whitespace-nowrap rounded-[3px] rounded-bl-none bg-primary px-1 py-px text-[0.5625rem] font-semibold leading-tight text-primary-foreground animate-in fade-in-0 duration-150 motion-reduce:animate-none"
        data-slot="doc-caret-tag"
      >
        {t.docPreview.caretName}
      </span>
      <span className={cn('inline-block h-[1.1em] w-0.5 translate-y-[0.2em] rounded-full bg-primary', PULSE)} />
    </span>
  )
}

export const DocMarkdown = memo(function DocMarkdown({ active, text }: { active?: boolean; text: string }) {
  const source = useMemo(() => normalizeDocMath(text), [text])
  const fence = useMemo(() => ({ openLine: active ? openFenceLine(source) : null }), [active, source])

  if (!text.trim()) {
    return null
  }

  return (
    <div className="wrap-anywhere" data-selectable-text="true">
      <DocFenceContext.Provider value={fence}>
        <Streamdown
          components={MARKDOWN_COMPONENTS}
          controls={false}
          mode="static"
          parseIncompleteMarkdown={Boolean(active)}
          plugins={PLUGINS}
        >
          {source}
        </Streamdown>
      </DocFenceContext.Provider>
    </div>
  )
})

function Bar({ className, width }: { className?: string; width: string }) {
  return <div className={cn('h-[0.8em] rounded bg-current/10', PULSE, className)} style={{ width }} />
}

/** Skeleton for a deck slide that has not been written yet. */
function SlideSkeleton() {
  return (
    <div className="grid size-full content-center gap-[3cqw] p-[6cqw]" style={{ fontSize: '2.4cqw' }}>
      <Bar className="h-[1.6em]" width="45%" />
      <div className="grid gap-[1.6cqw]">
        <Bar width="82%" />
        <Bar width="64%" />
        <Bar width="73%" />
      </div>
    </div>
  )
}

/** Skeleton for a document or PDF section: heading bar plus four uneven text bars. */
function SectionSkeleton() {
  return (
    <div className="grid gap-2.5 py-1" data-slot="doc-skeleton">
      <Bar className="h-4" width="38%" />
      <Bar width="96%" />
      <Bar width="88%" />
      <Bar width="93%" />
      <Bar width="54%" />
    </div>
  )
}

/** The content of a part fades in over its skeleton while the document streams. */
const FADE_IN = 'animate-in fade-in-0 duration-[120ms] motion-reduce:animate-none'

export interface ViewProps {
  doc: HarvisDoc
  parts: DocPart[]
  streaming: boolean
}

function PartCaption({ children, pending }: { children: string; pending?: boolean }) {
  return (
    <div className={cn('mb-1 truncate text-[0.625rem] font-medium text-muted-foreground', pending && 'italic')}>
      {children}
    </div>
  )
}

export function DeckView({ doc, parts, streaming }: ViewProps) {
  const { t } = useI18n()
  const copy = t.docPreview

  return (
    <div className="mx-auto grid max-w-3xl gap-6 px-4 py-4">
      {parts.map((part, i) => {
        const pending = part.state === 'pending'
        const { notes, text } = splitNotes(part.section?.body ?? '')
        const first = i === 0 && doc.kind === 'deck'

        return (
          <section data-part={i} data-state={part.state} key={`part-${i}`}>
            <PartCaption pending={pending}>
              {pending ? copy.pending(part.label) : `${copy.slide(i + 1)}${part.label ? ` · ${part.label}` : ''}`}
            </PartCaption>
            <div
              className="relative aspect-video overflow-hidden rounded-lg border border-border bg-card text-foreground shadow-sm"
              style={{ containerType: 'inline-size' }}
            >
              {pending ? (
                <div key="skeleton">
                  <SlideSkeleton />
                </div>
              ) : (
                <div
                  className={cn('flex size-full flex-col p-[6cqw]', first && 'justify-center', streaming && FADE_IN)}
                  key="content"
                  style={{ fontSize: first ? '3cqw' : '2.4cqw' }}
                >
                  {part.label && (
                    <h2
                      className={cn(
                        'mb-[0.6em] font-semibold leading-tight tracking-tight',
                        first ? 'text-[1.9em]' : 'text-[1.6em]'
                      )}
                    >
                      {part.label}
                    </h2>
                  )}
                  <DocMarkdown active={part.state === 'active'} text={text} />
                  {part.state === 'active' && <WritingCaret />}
                </div>
              )}
            </div>
            {notes && (
              <div className="mt-1.5 rounded-md bg-muted/40 px-2.5 py-1.5 text-[0.6875rem] leading-relaxed text-muted-foreground">
                <span className="font-semibold">{copy.notes}: </span>
                {notes}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}

function DocSection({ part, streaming }: { part: DocPart; streaming: boolean }) {
  const { t } = useI18n()

  if (part.state === 'pending') {
    return (
      <div key="skeleton">
        <PartCaption pending>{t.docPreview.pending(part.label)}</PartCaption>
        <SectionSkeleton />
      </div>
    )
  }

  return (
    <div className={cn(streaming && FADE_IN)} key="content">
      {part.label && <h2 className={cn(TAGS.h2, 'text-[1.25em]')}>{part.label}</h2>}
      <DocMarkdown active={part.state === 'active'} text={part.section?.body ?? ''} />
      {part.state === 'active' && <WritingCaret />}
    </div>
  )
}

export function DocView({ doc, parts, streaming }: ViewProps) {
  const { t } = useI18n()

  return (
    <article className="mx-auto max-w-3xl px-5 py-5 text-sm leading-relaxed text-foreground">
      <h1 className="mb-4 text-[1.7em] font-bold leading-tight tracking-tight">{doc.title || t.docPreview.untitled}</h1>
      <div className="grid gap-5">
        {parts.map((part, i) => (
          <section data-part={i} data-state={part.state} key={`part-${i}`}>
            <DocSection part={part} streaming={streaming} />
          </section>
        ))}
      </div>
    </article>
  )
}

const A4_RATIO = Math.SQRT2

/** Paper width and rendered content height, kept current as the page is laid out. */
function usePaperMetrics() {
  const paperRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const [metrics, setMetrics] = useState({ content: 0, width: 0 })

  useEffect(() => {
    const paper = paperRef.current
    const content = contentRef.current

    if (!paper || !content || typeof ResizeObserver === 'undefined') {
      return
    }

    const measure = () => setMetrics({ content: content.offsetHeight, width: paper.clientWidth })
    const observer = new ResizeObserver(measure)

    observer.observe(paper)
    observer.observe(content)
    measure()

    return () => observer.disconnect()
  }, [])

  return { contentRef, metrics, paperRef }
}

export function PdfView({ doc, parts, streaming }: ViewProps) {
  const { t } = useI18n()
  const copy = t.docPreview
  const { contentRef, metrics, paperRef } = usePaperMetrics()
  const pageHeight = metrics.width * A4_RATIO
  const pages = pageHeight > 0 ? Math.max(1, Math.ceil(metrics.content / pageHeight)) : 1

  return (
    <div className="px-3 py-4">
      <div
        className="relative mx-auto w-full max-w-190 overflow-hidden bg-white text-neutral-900 shadow-md ring-1 ring-black/10"
        data-slot="doc-paper"
        ref={paperRef}
        style={{ minHeight: pageHeight > 0 ? pages * pageHeight : undefined }}
      >
        <div className="px-[9%] py-[8%] text-[0.8125rem] leading-relaxed" ref={contentRef}>
          <h1 className="mb-[0.8em] text-[1.9em] font-bold leading-tight tracking-tight">
            {doc.title || copy.untitled}
          </h1>
          <div className="grid gap-[1.1em]">
            {parts.map((part, i) => (
              <section data-part={i} data-state={part.state} key={`part-${i}`}>
                <DocSection part={part} streaming={streaming} />
              </section>
            ))}
          </div>
        </div>
        {Array.from({ length: pages - 1 }, (_, i) => (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 border-t border-dashed border-neutral-400/70"
            data-slot="doc-page-break"
            key={`break-${i}`}
            style={{ top: (i + 1) * pageHeight }}
          >
            <span className="absolute right-2 top-0.5 text-[0.625rem] text-neutral-500">{copy.page(i + 2)}</span>
          </div>
        ))}
      </div>
      {streaming && (
        <p className="mx-auto mt-2 max-w-190 text-center text-[0.625rem] text-muted-foreground">
          {copy.paginationProvisional}
        </p>
      )}
    </div>
  )
}

/** Slide list shown above a deck: number and title per slide, dashed while unwritten. */
export function DeckStrip({
  onSelect,
  open,
  parts
}: {
  onSelect: (index: number) => void
  open: boolean
  parts: DocPart[]
}) {
  const { t } = useI18n()
  const copy = t.docPreview

  if (!open) {
    return null
  }

  return (
    <div
      aria-label={copy.slides}
      className="flex shrink-0 gap-1.5 overflow-x-auto border-b border-border/60 px-3 py-2"
      role="list"
    >
      {parts.map((part, i) => (
        <button
          className={cn(
            'w-24 shrink-0 rounded-md border px-2 py-1 text-left transition-colors hover:bg-accent',
            part.state === 'pending' ? 'border-dashed border-border text-muted-foreground' : 'border-border',
            part.state === 'active' && 'border-primary/60'
          )}
          key={`thumb-${i}`}
          onClick={() => onSelect(i)}
          role="listitem"
          type="button"
        >
          <span className="block text-[0.5625rem] tabular-nums text-muted-foreground">{i + 1}</span>
          <span className="block truncate text-[0.625rem] font-medium">{part.label || copy.slide(i + 1)}</span>
        </button>
      ))}
    </div>
  )
}
