import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { stubMenuDomApis } from '@/test/jsdom'
import { $liveDocs, clearLiveDocs } from '@/store/live-docs'
import { $previewTabs, closeRightRail } from '@/store/preview'
import { $activeSessionId, $selectedStoredSessionId } from '@/store/session'

import { DocCard } from './doc-card'

const HEADER = `---
kind: deck
title: Q3 Security Review
outline:
  - Title
  - Threat landscape
  - Next steps
---
`

const ONE_SLIDE = `${HEADER}# Q3 Security Review\n`
const TWO_SLIDES = `${ONE_SLIDE}---\n## Threat landscape\n- Phishing is up\n`

const KEY = 'session-card:q3-security-review'

const cardButton = () => document.querySelector('[data-slot="aui_doc-card"]') as HTMLButtonElement

function block(kind: string, title: string, body: string): string {
  return `---\nkind: ${kind}\ntitle: ${title}\n---\n${body}\n`
}

function tabUrls() {
  return $previewTabs.get().map(tab => tab.target.url)
}

describe('DocCard', () => {
  beforeEach(() => {
    $activeSessionId.set('session-card')
    $selectedStoredSessionId.set(null)
    window.localStorage.clear()
    stubMenuDomApis()
    clearLiveDocs()
    closeRightRail()
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    $activeSessionId.set(null)
    clearLiveDocs()
    closeRightRail()
  })

  it('shows the title and how far along the document is while streaming', () => {
    render(<DocCard code={TWO_SLIDES} streaming />)

    const card = cardButton()

    expect(card.dataset.slot).toBe('aui_doc-card')
    expect(card.dataset.streaming).toBe('true')
    expect(card.textContent).toContain('Q3 Security Review')
    expect(card.textContent).toContain('Writing slide 2 of 3')
  })

  it('says the document is starting before the header names it', () => {
    render(<DocCard code={'---\nkind: deck'} streaming />)

    expect(cardButton().textContent).toContain('Starting')
    expect(cardButton().hasAttribute('disabled')).toBe(true)
    expect($previewTabs.get()).toHaveLength(0)
  })

  it('opens the rail once while streaming, and not again after the tab is closed', () => {
    const { rerender } = render(<DocCard code={ONE_SLIDE} streaming />)

    expect(tabUrls()).toEqual([`doc:${KEY}`])

    closeRightRail()
    rerender(<DocCard code={TWO_SLIDES} streaming />)

    expect(tabUrls()).toEqual([])
  })

  it('keeps one document and one tab when a new chat gets its stored id mid-stream', () => {
    const { rerender } = render(<DocCard code={ONE_SLIDE} streaming />)

    act(() => $selectedStoredSessionId.set('stored-card'))
    rerender(<DocCard code={TWO_SLIDES} streaming />)

    expect(tabUrls()).toEqual([`doc:${KEY}`])
    expect(Object.keys($liveDocs.get())).toEqual([KEY])
    expect($liveDocs.get()[KEY].source).toBe(TWO_SLIDES)
  })

  it('registers the live document and keeps it current as tokens arrive', () => {
    const { rerender } = render(<DocCard code={ONE_SLIDE} streaming />)

    expect($liveDocs.get()[KEY]).toMatchObject({ source: ONE_SLIDE, streaming: true })

    rerender(<DocCard code={TWO_SLIDES} streaming={false} />)

    expect($liveDocs.get()[KEY]).toMatchObject({ source: TWO_SLIDES, streaming: false })
  })

  it('does not open the rail for a document that is already finished', () => {
    render(<DocCard code={TWO_SLIDES} streaming={false} />)

    expect(tabUrls()).toEqual([])
    expect(cardButton().textContent).toContain('Presentation · PPTX · 2 slides')
  })

  it('opens the rail on click', async () => {
    render(<DocCard code={TWO_SLIDES} streaming={false} />)

    await act(async () => {
      fireEvent.click(cardButton())
    })

    expect(tabUrls()).toEqual([`doc:${KEY}`])
  })

  it('names the file type on the second line of a finished card, per kind', () => {
    const cases: [string, string][] = [
      ['deck', 'Presentation · PPTX'],
      ['doc', 'Document · DOCX'],
      ['pdf', 'PDF · 1 section'],
      ['sheet', 'Spreadsheet · XLSX']
    ]

    for (const [kind, line] of cases) {
      const { unmount } = render(
        <DocCard code={block(kind, `A ${kind}`, kind === 'sheet' ? '## S\n| a |\n|---|\n| 1 |' : '## One\nText')} />
      )

      expect(cardButton().textContent).toContain(line)
      unmount()
    }
  })

  it('shows progress instead of a file type while the document is being written', () => {
    render(<DocCard code={TWO_SLIDES} streaming />)

    expect(cardButton().textContent).toContain('Presentation · Writing slide 2 of 3')
    expect(cardButton().textContent).not.toContain('PPTX')
  })

  it('disables the download with "Writing…" while streaming and enables it when done', () => {
    const { rerender } = render(<DocCard code={TWO_SLIDES} streaming />)

    const download = () => document.querySelector('[data-slot="doc-export"] button') as HTMLButtonElement

    expect(download().disabled).toBe(true)
    expect(download().textContent).toBe('Writing…')

    rerender(<DocCard code={TWO_SLIDES} streaming={false} />)

    expect(download().disabled).toBe(false)
    expect(download().textContent).toBe('Download .pptx')
  })

  it('offers each kind its other formats in the dropdown', async () => {
    const cases: [string, string[]][] = [
      ['deck', ['PowerPoint', 'PDF']],
      ['doc', ['Word', 'PDF', 'Markdown']],
      ['pdf', ['PDF', 'Word']],
      ['sheet', ['Excel', 'CSV']]
    ]

    for (const [kind, labels] of cases) {
      const { unmount } = render(<DocCard code={block(kind, `A ${kind}`, '## One\nText')} />)

      fireEvent.pointerDown(screen.getByLabelText('More formats'), { button: 0, ctrlKey: false, pointerType: 'mouse' })

      const items = await screen.findAllByRole('menuitem')

      expect(items.map(item => item.querySelector('span')?.textContent)).toEqual(labels)
      fireEvent.keyDown(items[0], { key: 'Escape' })
      unmount()
    }
  })

  it('downloads the card document and reports a failure with a retry', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ detail: 'no converter' }), { status: 400 }))

    vi.stubGlobal('fetch', fetchMock)
    render(<DocCard code={TWO_SLIDES} />)

    fireEvent.click(screen.getByText('Download .pptx'))

    await waitFor(() => expect(screen.getByText(/Export failed · Retry/)).toBeTruthy())
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toMatchObject({
      format: 'pptx',
      source: TWO_SLIDES
    })
  })
})
