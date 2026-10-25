import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { closedHarvisDocFences } from '@/lib/harvis-doc-files'
import { $liveDocs, clearLiveDocs } from '@/store/live-docs'
import { $activeSessionId, $selectedStoredSessionId } from '@/store/session'
import { stubMenuDomApis, stubResizeObserver } from '@/test/jsdom'

// `real` hands the hook back to assistant-ui, so a MarkdownTextContent provides the text itself.
const part = vi.hoisted(() => ({ real: false, text: '' }))

vi.mock('@assistant-ui/react', async importOriginal => {
  const original = await importOriginal<typeof import('@assistant-ui/react')>()

  return {
    ...original,
    useMessagePartText: () => (part.real ? original.useMessagePartText() : { text: part.text })
  }
})

import { OpenDocFenceContext, TranscriptDocCard } from './doc-card'
import { MarkdownTextContent } from './markdown-text'

const BODY = '---\nkind: deck\ntitle: Q3 Review\n---\n# Q3 Review\n---\n## Threats\n- Phishing\n'
const KEY = 'session-card:q3-review'

const liveDoc = () => $liveDocs.get()[KEY]

describe('TranscriptDocCard cut-off detection', () => {
  beforeEach(() => {
    $activeSessionId.set('session-card')
    $selectedStoredSessionId.set(null)
    window.localStorage.clear()
    stubMenuDomApis()
    stubResizeObserver()
    clearLiveDocs()
  })

  afterEach(() => {
    cleanup()
    $activeSessionId.set(null)
    clearLiveDocs()
  })

  it('marks a fence the turn never closed (Stop) as cut off, not as a finished document', () => {
    part.text = `\`\`\`harvis-doc\n${BODY}`

    render(
      <OpenDocFenceContext.Provider value={BODY}>
        <TranscriptDocCard code={BODY} running />
      </OpenDocFenceContext.Provider>
    )
    expect(liveDoc()).toMatchObject({ cutOff: false, streaming: true })

    // Stop: the message is no longer running and nothing closed the fence.
    cleanup()
    render(
      <OpenDocFenceContext.Provider value={null}>
        <TranscriptDocCard code={BODY} running={false} />
      </OpenDocFenceContext.Provider>
    )
    expect(liveDoc()).toMatchObject({ cutOff: true, streaming: false })
  })

  it('does not mark a closed fence as cut off, in a running message or a finished one', () => {
    part.text = `\`\`\`harvis-doc\n${BODY}\`\`\`\nAnd a summary.`

    const view = render(
      <OpenDocFenceContext.Provider value={null}>
        <TranscriptDocCard code={BODY} running />
      </OpenDocFenceContext.Provider>
    )

    expect(liveDoc()).toMatchObject({ cutOff: false, streaming: false })

    view.rerender(
      <OpenDocFenceContext.Provider value={null}>
        <TranscriptDocCard code={BODY} running={false} />
      </OpenDocFenceContext.Provider>
    )
    expect(liveDoc()).toMatchObject({ cutOff: false, streaming: false })
  })
})

// The card's code comes through the markdown preprocessor (trailing spaces, indent and list
// prefixes dropped); the message text it is matched against is raw.
describe('a closed fence that the markdown preprocessor rewrites', () => {
  const HEAD = '---\nkind: deck\ntitle: Q3 Review\n---\n'
  const indent = (text: string, pad: string) => text.replace(/^(?=.)/gm, pad)

  const variants: Array<[string, string]> = [
    ['trailing spaces on a line', `Here:\n\n\`\`\`\`harvis-doc\n${HEAD}# Q3 Review  \nNotes: hi\n---\n## End\n- done\t\n\`\`\`\`\n\nDone.`],
    ['an indented fence', `Here:\n\n  \`\`\`harvis-doc\n${indent(`${HEAD}# Q3 Review  \n---\n## End\n- done\n`, '  ')}  \`\`\`\n`],
    ['a fence in a list item', `1. Deck:\n\n   \`\`\`harvis-doc\n${indent(`${HEAD}# Q3 Review\n---\n## End\n- done\n`, '   ')}   \`\`\`\n`]
  ]

  beforeEach(() => {
    part.real = true
    $activeSessionId.set('session-card')
    $selectedStoredSessionId.set(null)
    window.localStorage.clear()
    stubMenuDomApis()
    stubResizeObserver()
    clearLiveDocs()
  })

  afterEach(() => {
    part.real = false
    cleanup()
    $activeSessionId.set(null)
    clearLiveDocs()
  })

  for (const [name, text] of variants) {
    it(`is not cut off, rendered through the real markdown: ${name}`, async () => {
      render(<MarkdownTextContent isRunning={false} text={text} />)
      await screen.findAllByText('Q3 Review')

      expect(Object.values($liveDocs.get())).toEqual([expect.objectContaining({ cutOff: false, streaming: false })])
    })
  }

  it('still reads a fence the turn never closed as cut off, through the real markdown', async () => {
    const text = `Here:\n\n\`\`\`harvis-doc\n${HEAD}# Q3 Review  \n---\n## En`

    render(<MarkdownTextContent isRunning={false} text={text} />)
    await screen.findAllByText('Q3 Review')

    expect(Object.values($liveDocs.get())).toEqual([expect.objectContaining({ cutOff: true })])
  })

  it('finds a fence in a list item or a bullet, with its indent removed from the body', () => {
    const body = `${HEAD}# Q3 Review\n- done\n`

    expect(closedHarvisDocFences(`- Deck:\n  - \`\`\`harvis-doc\n${indent(body, '    ')}    \`\`\`\n`)).toEqual([body.trimEnd()])
    expect(closedHarvisDocFences(`1. Deck:\n\n   \`\`\`harvis-doc\n${indent(body, '   ')}   \`\`\`\n`)).toEqual([body.trimEnd()])
  })
})
