import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { closedHarvisDocFences } from '@/lib/harvis-doc-files'
import { clearLiveDocs } from '@/store/live-docs'
import { closeRightRail } from '@/store/preview'
import { $activeSessionId } from '@/store/session'

import { DocDownloadAll } from './doc-card'
import { MarkdownTextContent } from './markdown-text'

const DECK = '---\nkind: deck\ntitle: Q3 Review\n---\n# Q3 Review\n'
const MEMO = '---\nkind: doc\ntitle: Memo\n---\n## Summary\nShort.\n'
const BUDGET = '---\nkind: sheet\ntitle: Budget\n---\n## Income\n| a |\n|---|\n| 1 |\n'

const fence = (body: string, close = true) => `\`\`\`\`harvis-doc\n${body}${close ? '````\n' : ''}`

// jsdom's Blob is not the one Node's Response can read.
const okFile = () => ({ blob: async () => new Blob(['x']), headers: new Headers(), ok: true, status: 200 })

const downloadAll = () => document.querySelector('[data-slot="aui_doc-download-all"]')

describe('closedHarvisDocFences', () => {
  it('returns only the fenced documents that have closed', () => {
    const text = `Intro\n\n${fence(DECK)}\nBetween\n\n${fence(MEMO)}\n\`\`\`ts\nlet x\n\`\`\`\n\n${fence(BUDGET, false)}`

    expect(closedHarvisDocFences(text)).toEqual([DECK.trimEnd(), MEMO.trimEnd()])
  })

  it('is empty for a message with no document', () => {
    expect(closedHarvisDocFences('just text\n```ts\nlet x\n```')).toEqual([])
  })
})

describe('Download all', () => {
  beforeEach(() => {
    $activeSessionId.set('session-all')
    window.localStorage.clear()
    clearLiveDocs()
    closeRightRail()
  })

  afterEach(() => {
    cleanup()
    $activeSessionId.set(null)
    clearLiveDocs()
    closeRightRail()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('appears once a message holds two finished documents', async () => {
    render(<MarkdownTextContent isRunning={false} text={`${fence(DECK)}\n${fence(MEMO)}`} />)

    await screen.findByText('Q3 Review')

    expect(document.querySelectorAll('[data-slot="aui_doc-card"]')).toHaveLength(2)
    expect(document.querySelectorAll('[data-slot="aui_doc-download-all"]')).toHaveLength(1)
    expect(screen.getByText('Download all')).toBeTruthy()
  })

  it('is absent for a single document', async () => {
    render(<MarkdownTextContent isRunning={false} text={fence(DECK)} />)

    await screen.findByText('Q3 Review')

    expect(downloadAll()).toBeNull()
  })

  it('waits for the second document to finish', async () => {
    const { rerender } = render(
      <MarkdownTextContent isRunning text={`${fence(DECK)}\nAnd the memo:\n\n${fence(MEMO, false)}`} />
    )

    await screen.findByText('Q3 Review')

    expect(downloadAll()).toBeNull()

    rerender(<MarkdownTextContent isRunning text={`${fence(DECK)}\nAnd the memo:\n\n${fence(MEMO)}`} />)

    await waitFor(() => expect(downloadAll()).not.toBeNull())
  })

  it('downloads every document in its main format and keeps going past a failure', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }))
      .mockImplementation(async () => okFile())

    vi.stubGlobal('fetch', fetchMock)
    URL.createObjectURL = () => 'blob:x'
    URL.revokeObjectURL = () => undefined
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    render(
      <DocDownloadAll
        files={[
          { kind: 'deck', source: DECK, title: 'Q3 Review' },
          { kind: 'doc', source: MEMO, title: 'Memo' },
          { kind: 'sheet', source: BUDGET, title: 'Budget' }
        ]}
      />
    )

    fireEvent.click(screen.getByText('Download all'))

    await waitFor(() => expect(screen.getByText('1 file failed to download')).toBeTruthy())

    const formats = fetchMock.mock.calls.map(call => JSON.parse((call[1] as RequestInit).body as string).format)

    expect(formats).toEqual(['pptx', 'docx', 'xlsx'])
  })
})
