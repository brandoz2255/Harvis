import { createContext } from 'react'

import { scanFences } from '@/lib/harvis-doc-blocks'
import { createMemoizedMathPlugin } from '@/lib/katex-memo'
import { normalizeFilePreviewMath } from '@/lib/markdown-preprocess'

/** Which fence is still being written: the line it opens on, or null when every fence is closed or the part is done. */
export const DocFenceContext = createContext<{ openLine: number | null }>({ openLine: null })

// Module scope so Streamdown's plugin identity never changes between renders.
export const docMathPlugin = createMemoizedMathPlugin({ singleDollarTextMath: true })

/**
 * Math delimiter and currency-dollar normalisation for a document body. An
 * unclosed trailing fence is left alone: the normaliser pairs fences itself
 * and would otherwise rewrite `$` inside code that has not finished arriving.
 */
export function normalizeDocMath(text: string): string {
  const open = scanFences(text).find(fence => !fence.closed)

  return open
    ? normalizeFilePreviewMath(text.slice(0, open.offset)) + text.slice(open.offset)
    : normalizeFilePreviewMath(text)
}

/** Line of the fence that is still open at the end of `text`, or null. */
export function openFenceLine(text: string): number | null {
  const last = scanFences(text).at(-1)

  return last && !last.closed ? last.line : null
}
