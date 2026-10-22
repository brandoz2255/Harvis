import { Children, type ComponentProps, isValidElement, type ReactNode, useContext } from 'react'

import { RICH_FENCE_LANGUAGES, RichCodeBlock } from '@/components/assistant-ui/embeds/registry'
import { docBlockKind } from '@/lib/harvis-doc-blocks'
import { cn } from '@/lib/utils'

import { BlockSkeleton } from './block-skeleton'
import { DocBlock } from './doc-block'
import { DocCodeFence } from './code-fence'
import { DocFenceContext } from './fence-context'
import { nodeText } from './status-chip'

interface MdNode {
  position?: { start?: { line?: number } }
}

/**
 * Replaces Streamdown's `<pre><code class="language-x">`: block fences become
 * drawings (or a skeleton while still open), mermaid/svg use the shared
 * renderers, everything else is a labelled, highlighted code card.
 */
export function DocPre({ children, node }: ComponentProps<'pre'> & { node?: MdNode }) {
  const { openLine } = useContext(DocFenceContext)
  const child = Children.toArray(children)[0]

  if (!isValidElement<{ children?: ReactNode; className?: string }>(child)) {
    return <pre>{children}</pre>
  }

  const language = /language-([^\s]+)/.exec(child.props.className ?? '')?.[1] ?? ''
  const code = nodeText(child.props.children).replace(/\n$/, '')
  const writing = openLine !== null && node?.position?.start?.line === openLine
  const kind = docBlockKind(language)

  if (kind) {
    return writing ? <BlockSkeleton kind={kind} /> : <DocBlock code={code} kind={kind} />
  }

  const fence = <DocCodeFence code={code} language={language} writing={writing} />

  return RICH_FENCE_LANGUAGES.has(language.toLowerCase()) && !writing ? (
    <RichCodeBlock code={code} fallback={fence} language={language} />
  ) : (
    fence
  )
}

/** Read-only checkbox for `- [ ]` / `- [x]` task items. */
export function DocCheckbox({ checked, type }: ComponentProps<'input'>) {
  if (type !== 'checkbox') {
    return null
  }

  return (
    <span
      aria-checked={Boolean(checked)}
      aria-disabled
      className={cn(
        'mr-[0.5em] inline-grid size-[1.05em] translate-y-[0.18em] place-items-center rounded-[0.28em] border align-baseline',
        checked ? 'border-primary bg-primary text-primary-foreground' : 'border-current/40 bg-transparent'
      )}
      data-checked={checked ? 'true' : 'false'}
      data-slot="doc-checkbox"
      role="checkbox"
    >
      {checked && (
        <svg
          aria-hidden
          className="size-[0.75em]"
          fill="none"
          stroke="currentColor"
          strokeWidth={3.5}
          viewBox="0 0 16 16"
        >
          <path d="M3 8.5l3.2 3.2L13 4.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </span>
  )
}
