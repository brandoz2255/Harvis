import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { stubMenuDomApis, stubResizeObserver } from '@/test/jsdom'
import { $liveDocs, clearLiveDocs, liveDocTarget, upsertLiveDoc } from '@/store/live-docs'

import { DocumentPreview } from './preview-document'

const KEY = 'session-view:q3-security-review'

const DECK_HEADER = `---
kind: deck
title: Q3 Security Review
outline:
  - Title
  - Threat landscape
  - Next steps
  - Close
---
`

const DECK_TWO = `${DECK_HEADER}# Q3 Security Review\nNotes: open warmly\n---\n## Threat landscape\n- Phishing is up\n`

const SHEET = `---
kind: sheet
title: Budget
outline:
  - Income
  - Expenses
---
## Income
| Month | Amount |
|---|---|
| Jan | 1200 |
| Feb | =B2*2 |
`

function show(source: string, streaming: boolean, key = KEY) {
  act(() => upsertLiveDoc(key, 'session-view', source, streaming))
}

function renderPreview(key = KEY) {
  return render(<DocumentPreview target={liveDocTarget(key, 'Q3 Security Review')} />)
}

describe('DocumentPreview', () => {
  beforeEach(() => {
    stubResizeObserver()
    stubMenuDomApis()
    clearLiveDocs()
  })

  afterEach(() => {
    cleanup()
    clearLiveDocs()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('says so when the document is no longer in memory', () => {
    renderPreview()

    expect(screen.getByText('Document unavailable')).toBeTruthy()
  })

  it('shows one skeleton per outline entry that has not been written yet', () => {
    show(DECK_TWO, true)
    const { container } = renderPreview()

    expect(container.querySelectorAll('[data-part]')).toHaveLength(4)
    expect(container.querySelectorAll('[data-part][data-state="pending"]')).toHaveLength(2)
    expect(screen.getByText('Next steps (not written yet)')).toBeTruthy()
    expect(screen.getByText('Close (not written yet)')).toBeTruthy()
    expect(container.querySelectorAll('[data-slot="doc-caret"]')).toHaveLength(1)
  })

  it('fills the skeletons in as parts arrive', () => {
    show(DECK_TWO, true)
    const { container } = renderPreview()

    show(`${DECK_TWO}---\n## Next steps\n1. Passkeys\n`, true)

    expect(container.querySelectorAll('[data-part][data-state="pending"]')).toHaveLength(1)
    expect(container.textContent).toContain('Writing slide 3 of 4')
  })

  it('drops the skeletons when the stream ends and shows speaker notes', () => {
    show(DECK_TWO, true)
    const { container } = renderPreview()

    show(DECK_TWO, false)

    expect(container.querySelectorAll('[data-part]')).toHaveLength(2)
    expect(container.querySelector('[data-slot="doc-caret"]')).toBeNull()
    expect(screen.getByText('open warmly')).toBeTruthy()
    expect(screen.getByText('Done')).toBeTruthy()
  })

  it('disables the download while writing and offers the kind formats once done', () => {
    show(DECK_TWO, true)
    renderPreview()

    const exportButton = () => document.querySelector('[data-slot="doc-export"] button') as HTMLButtonElement

    expect(exportButton().disabled).toBe(true)
    expect(exportButton().textContent).toBe('Writing…')

    show(DECK_TWO, false)

    const download = screen.getByText('Download .pptx').closest('button') as HTMLButtonElement

    expect(download.disabled).toBe(false)
  })

  it('downloads through the export endpoint and reports failure with a retry', async () => {
    show(DECK_TWO, false)
    renderPreview()

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'no converter' }), { status: 400 }))
      .mockResolvedValueOnce({
        blob: async () => new Blob(['x']),
        headers: new Headers({ 'Content-Disposition': 'attachment; filename="deck.pptx"' }),
        ok: true,
        status: 200
      })

    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => undefined }))
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    fireEvent.click(screen.getByText('Download .pptx'))

    await waitFor(() => expect(screen.getByText(/Export failed/)).toBeTruthy())

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]

    expect(url).toBe('/hermes-api/api/harvis/docs/export')
    expect(JSON.parse(init.body as string)).toMatchObject({
      format: 'pptx',
      source: DECK_TWO,
      title: 'Q3 Security Review'
    })

    fireEvent.click(screen.getByText(/Export failed/))

    await waitFor(() => expect(screen.getByText('Downloaded')).toBeTruthy())
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('lays a sheet out as a grid with column letters, row numbers and a formula bar', () => {
    show(SHEET, true)
    const { container } = renderPreview()

    const headers = Array.from(container.querySelectorAll('thead th')).map(th => th.textContent)

    expect(headers.slice(1, 6)).toEqual(['A', 'B', 'C', 'D', 'E'])
    expect(container.querySelectorAll('tbody tr').length).toBeGreaterThanOrEqual(12)
    expect(screen.getByRole('tab', { name: 'Income' })).toBeTruthy()
    expect((screen.getByRole('tab', { name: 'Expenses' }) as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(screen.getByText('=B2*2'))

    expect(screen.getByLabelText('Formula bar').textContent).toBe('B3')
    expect(container.querySelector('[data-slot="doc-formula-bar"]')?.textContent).toContain('=B2*2')
  })

  it('lays a pdf out on a paper page and warns that page breaks are provisional while writing', () => {
    const pdf = '---\nkind: pdf\ntitle: Memo\noutline: [Summary, Details]\n---\n## Summary\nShort.\n'

    show(pdf, true)
    const { container } = renderPreview()

    expect(container.querySelector('[data-slot="doc-paper"]')).toBeTruthy()
    expect(container.querySelectorAll('[data-part][data-state="pending"]')).toHaveLength(1)
    expect(screen.getByText(/Page breaks are provisional/)).toBeTruthy()

    show(pdf, false)

    expect(screen.queryByText(/Page breaks are provisional/)).toBeNull()
  })

  it('treats a stream that stopped updating as finished', () => {
    vi.useFakeTimers()

    try {
      show(DECK_TWO, true)
      renderPreview()

      expect(screen.getByText('Writing…', { selector: '[data-slot="doc-status"]' })).toBeTruthy()

      act(() => {
        vi.advanceTimersByTime(45_000)
      })

      expect(screen.getByText('Done')).toBeTruthy()
      expect($liveDocs.get()[KEY].streaming).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })
})
