import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { $liveDocs, clearLiveDocs } from '@/store/live-docs'
import { $previewTabs, closeRightRail } from '@/store/preview'
import { $activeSessionId, $selectedStoredSessionId } from '@/store/session'

import { MarkdownTextContent } from './markdown-text'

const HEADER = `---
kind: deck
title: Q3 Security Review
outline:
  - Title
  - Threat landscape
  - Next steps
---
`

const TWO_SLIDES = `${HEADER}# Q3 Security Review
Notes: open warmly
---
## Threat landscape
- Phishing is up
`

function fenced(body: string, close = true): string {
  return `Here is the deck:\n\n\`\`\`\`harvis-doc\n${body}${close ? '\n````\n' : ''}`
}

// The fence arrives token by token. Streamdown must hand the UNCLOSED fence to
// the SyntaxHighlighter override with its language, or the card (and the
// rail that opens from it) would only appear once the whole document is done.
describe('MarkdownTextContent harvis-doc fences', () => {
  beforeEach(() => {
    $activeSessionId.set('session-docs')
    $selectedStoredSessionId.set(null)
    window.localStorage.clear()
    clearLiveDocs()
    closeRightRail()
  })

  afterEach(() => {
    cleanup()
    $activeSessionId.set(null)
    clearLiveDocs()
    closeRightRail()
  })

  it('renders an unclosed fence as a streaming doc card and opens the rail', async () => {
    const { container } = render(<MarkdownTextContent isRunning text={fenced(TWO_SLIDES, false)} />)

    const card = await screen.findByText('Q3 Security Review')

    expect(card.closest('button')?.dataset.slot).toBe('aui_doc-card')
    expect(card.closest('button')?.dataset.streaming).toBe('true')
    expect(container.textContent).toContain('Writing slide 2 of 3')
    expect(Object.keys($liveDocs.get())).toEqual(['session-docs:q3-security-review'])
    expect($previewTabs.get().map(tab => tab.target.url)).toEqual(['doc:session-docs:q3-security-review'])
  })

  it('treats a closed fence as finished even while the message keeps streaming', async () => {
    const { container } = render(
      <MarkdownTextContent isRunning text={`${fenced(TWO_SLIDES)}\nThat is the deck. Want changes?`} />
    )

    const card = await screen.findByText('Q3 Security Review')

    expect(card.closest('button')?.dataset.streaming).toBe('false')
    expect(container.textContent).toContain('2 slides')
    expect($previewTabs.get()).toHaveLength(0)
  })

  it('renders a second document that is still streaming after a finished one as cards, not raw text', async () => {
    const second = TWO_SLIDES.replaceAll('Q3 Security Review', 'Cost Review')
    const text = `${fenced(TWO_SLIDES)}\nAnd a second one:\n\n\`\`\`\`harvis-doc\n${second}`

    const { container } = render(<MarkdownTextContent isRunning text={text} />)

    const first = await screen.findByText('Q3 Security Review')
    const next = await screen.findByText('Cost Review')

    expect(first.closest('button')?.dataset.streaming).toBe('false')
    expect(next.closest('button')?.dataset.streaming).toBe('true')
    expect(container.textContent).not.toContain('harvis-doc')
    expect(container.textContent).not.toContain('kind: deck')
  })

  it('accepts the harvisdoc spelling and a three-backtick fence', async () => {
    render(<MarkdownTextContent isRunning={false} text={`\`\`\`HarvisDoc\n${TWO_SLIDES}\n\`\`\`\n`} />)

    const card = await screen.findByText('Q3 Security Review')

    expect(card.closest('button')?.dataset.slot).toBe('aui_doc-card')
  })
})
