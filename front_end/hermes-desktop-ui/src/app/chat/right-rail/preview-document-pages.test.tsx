import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $liveDocs, clearLiveDocs, liveDocTarget, upsertLiveDoc } from '@/store/live-docs'
import { stubMenuDomApis, stubResizeObserver } from '@/test/jsdom'

import { DocumentPreview } from './preview-document'
import { PAGES_REFRESH_DEBOUNCE_MS } from './preview-document-pages'

const KEY = 'session-pages:q3-security-review'

const DECK = `---
kind: deck
title: Q3 Security Review
outline:
  - Title
  - Threat landscape
---
# Q3 Security Review
---
## Threat landscape
- Phishing is up
`

const PREVIEW_URL = '/hermes-api/api/harvis/docs/preview'

const previewBody = (count: number) => ({
  format: 'pptx',
  page_count: count,
  pages: Array.from({ length: count }, (_, index) => ({
    height: 540,
    index,
    url: `${PREVIEW_URL}/abc/${index}.png`,
    width: 960
  }))
})

// jsdom's Blob is not the one Node's Response can read, so answer with plain objects.
const png = () => ({ blob: async () => new Blob(['png']), headers: new Headers(), ok: true, status: 200 })

const json = (body: unknown, status = 200) => ({
  headers: new Headers(),
  json: async () => body,
  ok: status < 400,
  status,
  statusText: String(status)
})

type Router = (url: string, init?: RequestInit) => ReturnType<typeof json> | ReturnType<typeof png>

function install(router: Router) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => router(url, init))

  vi.stubGlobal('fetch', fetchMock)

  return fetchMock
}

const previewCalls = (fetchMock: ReturnType<typeof install>) =>
  fetchMock.mock.calls.filter(([url]) => url === PREVIEW_URL)

const imageCalls = (fetchMock: ReturnType<typeof install>) =>
  fetchMock.mock.calls.filter(([url]) => (url as string).endsWith('.png'))

function show(source: string, streaming: boolean) {
  act(() => upsertLiveDoc(KEY, 'session-pages', source, streaming))
}

function renderPanel() {
  return render(<DocumentPreview target={liveDocTarget(KEY, 'Q3 Security Review')} />)
}

const switchTo = (name: 'Live' | 'Preview') => fireEvent.click(screen.getByRole('button', { name }))
const pageLabel = () => document.querySelector('[data-slot="doc-pages"] [aria-live]')?.textContent

describe('document page preview', () => {
  const urlCreate = URL.createObjectURL
  const urlRevoke = URL.revokeObjectURL
  let created: string[]
  let revoked: string[]

  beforeEach(() => {
    stubResizeObserver()
    stubMenuDomApis()
    clearLiveDocs()
    created = []
    revoked = []
    URL.createObjectURL = () => {
      created.push(`blob:page-${created.length}`)

      return created[created.length - 1]
    }
    URL.revokeObjectURL = url => void revoked.push(url)
  })

  afterEach(() => {
    cleanup()
    clearLiveDocs()
    URL.createObjectURL = urlCreate
    URL.revokeObjectURL = urlRevoke
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('does not touch the preview endpoint until the Preview tab is chosen', async () => {
    const fetchMock = install(url => (url === PREVIEW_URL ? json(previewBody(2)) : png()))

    show(DECK, false)
    renderPanel()

    expect(previewCalls(fetchMock)).toHaveLength(0)

    switchTo('Preview')

    await waitFor(() => expect(pageLabel()).toBe('Page 1 / 2'))
    expect(previewCalls(fetchMock)).toHaveLength(1)

    const [, init] = previewCalls(fetchMock)[0]

    expect(init?.credentials).toBe('include')
    expect(JSON.parse(init?.body as string)).toMatchObject({
      format: 'pptx',
      source: DECK,
      title: 'Q3 Security Review'
    })
  })

  it('does not fetch while the document is still being written, and fetches when it finishes', async () => {
    const fetchMock = install(url => (url === PREVIEW_URL ? json(previewBody(2)) : png()))

    show(DECK, true)
    renderPanel()
    switchTo('Preview')

    expect(screen.getByText('Preview is available once the document is written')).toBeTruthy()

    show(`${DECK}---\n## More\n- x\n`, true)
    expect(fetchMock).not.toHaveBeenCalled()

    show(`${DECK}---\n## More\n- x\n`, false)

    await waitFor(() => expect(pageLabel()).toBe('Page 1 / 2'))
    expect(previewCalls(fetchMock)).toHaveLength(1)
  })

  it('shows a page-shaped skeleton while rendering', async () => {
    let release: (value: unknown) => void = () => undefined

    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(resolve => (release = resolve)))
    )

    show(DECK, false)
    renderPanel()
    switchTo('Preview')

    const skeleton = document.querySelector('[data-slot="doc-pages-skeleton"] > div') as HTMLElement

    expect(skeleton.style.aspectRatio).toBe('16 / 9')

    await act(async () => release(json(previewBody(1))))
  })

  it('walks the pages with the buttons and the arrow keys, fetching each image with the session cookie', async () => {
    const fetchMock = install(url => (url === PREVIEW_URL ? json(previewBody(3)) : png()))

    show(DECK, false)
    renderPanel()
    switchTo('Preview')

    await waitFor(() => expect(pageLabel()).toBe('Page 1 / 3'))

    const img = () => document.querySelector('[data-slot="doc-pages"] img') as HTMLImageElement
    const prev = screen.getByLabelText('Previous page') as HTMLButtonElement
    const next = screen.getByLabelText('Next page') as HTMLButtonElement

    await waitFor(() => expect(img().src).toBe('blob:page-0'))
    expect(img().style.width).toBe('100%')
    expect(img().getAttribute('loading')).toBe('lazy')
    expect(img().alt).toBe('Q3 Security Review, page 1 of 3')
    expect(prev.disabled).toBe(true)

    // The current page and the next are fetched; the third waits its turn.
    await waitFor(() => expect(imageCalls(fetchMock)).toHaveLength(2))
    expect(imageCalls(fetchMock)[0][1]).toMatchObject({ credentials: 'include' })

    fireEvent.click(next)
    await waitFor(() => expect(pageLabel()).toBe('Page 2 / 3'))
    await waitFor(() => expect(imageCalls(fetchMock)).toHaveLength(3))

    const pages = document.querySelector('[data-slot="doc-pages"]') as HTMLElement

    fireEvent.keyDown(pages, { key: 'ArrowRight' })
    expect(pageLabel()).toBe('Page 3 / 3')
    expect(next.disabled).toBe(true)

    fireEvent.keyDown(pages, { key: 'ArrowRight' })
    expect(pageLabel()).toBe('Page 3 / 3')

    fireEvent.keyDown(pages, { key: 'ArrowLeft' })
    fireEvent.keyDown(pages, { key: 'ArrowLeft' })
    expect(pageLabel()).toBe('Page 1 / 3')
  })

  it('says so when the document has more pages than were drawn', async () => {
    const body = { ...previewBody(2), page_count: 30 }

    install(url => (url === PREVIEW_URL ? json(body) : png()))
    show(DECK, false)
    renderPanel()
    switchTo('Preview')

    await waitFor(() => expect(pageLabel()).toBe('Page 1 / 2'))
    expect(document.querySelector('[data-slot="doc-pages-truncated"]')?.textContent).toBe(
      'Showing the first 2 of 30 pages'
    )
  })

  it('shows no truncation note when every page was drawn', async () => {
    install(url => (url === PREVIEW_URL ? json(previewBody(2)) : png()))
    show(DECK, false)
    renderPanel()
    switchTo('Preview')

    await waitFor(() => expect(pageLabel()).toBe('Page 1 / 2'))
    expect(document.querySelector('[data-slot="doc-pages-truncated"]')).toBeNull()
  })

  it('keeps the rendered pages when switching back to Live and again to Preview', async () => {
    const fetchMock = install(url => (url === PREVIEW_URL ? json(previewBody(1)) : png()))

    show(DECK, false)
    renderPanel()
    switchTo('Preview')
    await waitFor(() => expect(pageLabel()).toBe('Page 1 / 1'))

    switchTo('Live')
    expect(document.querySelectorAll('[data-part]').length).toBeGreaterThan(0)
    switchTo('Preview')

    expect(pageLabel()).toBe('Page 1 / 1')
    expect(previewCalls(fetchMock)).toHaveLength(1)
  })

  it('re-renders a finished document after its source settles, not on every change', async () => {
    const fetchMock = install(url => (url === PREVIEW_URL ? json(previewBody(1)) : png()))

    show(DECK, false)
    renderPanel()
    switchTo('Preview')
    await waitFor(() => expect(previewCalls(fetchMock)).toHaveLength(1))
    await waitFor(() => expect(pageLabel()).toBe('Page 1 / 1'))

    vi.useFakeTimers()

    show(`${DECK}\n- one\n`, false)
    await act(async () => void (await vi.advanceTimersByTimeAsync(PAGES_REFRESH_DEBOUNCE_MS - 100)))
    show(`${DECK}\n- one\n- two\n`, false)
    await act(async () => void (await vi.advanceTimersByTimeAsync(PAGES_REFRESH_DEBOUNCE_MS - 100)))

    expect(previewCalls(fetchMock)).toHaveLength(1)

    await act(async () => void (await vi.advanceTimersByTimeAsync(200)))

    expect(previewCalls(fetchMock)).toHaveLength(2)
    expect(JSON.parse(previewCalls(fetchMock)[1][1]?.body as string).source).toBe(`${DECK}\n- one\n- two\n`)
    expect($liveDocs.get()[KEY].streaming).toBe(false)
  })

  it('revokes its image URLs when it unmounts', async () => {
    install(url => (url === PREVIEW_URL ? json(previewBody(1)) : png()))

    show(DECK, false)

    const { unmount } = renderPanel()

    switchTo('Preview')
    await waitFor(() => expect(created).toHaveLength(1))

    unmount()

    expect(revoked).toEqual(['blob:page-0'])
  })

  it('says the sandbox is needed on a 503 and leaves the live view usable', async () => {
    const fetchMock = install(url => (url === PREVIEW_URL ? json({ detail: 'sandbox unavailable' }, 503) : png()))

    show(DECK, false)
    renderPanel()
    switchTo('Preview')

    await screen.findByText('Preview needs the document sandbox')
    expect(screen.queryByText('sandbox unavailable')).toBeNull()

    switchTo('Live')

    expect(document.querySelectorAll('[data-part]').length).toBeGreaterThan(0)
    expect((screen.getByText('Download .pptx').closest('button') as HTMLButtonElement).disabled).toBe(false)

    // Coming back to Preview asks again; the sandbox is still down.
    switchTo('Preview')
    await screen.findByText('Preview needs the document sandbox')
    await waitFor(() => expect(previewCalls(fetchMock)).toHaveLength(2))

    fetchMock.mockImplementation(async (url: string) => (url === PREVIEW_URL ? json(previewBody(1)) : png()))
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => expect(pageLabel()).toBe('Page 1 / 1'))
  })

  it('reports any other failure with its own message', async () => {
    install(() => json({ detail: 'render crashed' }, 500))

    show(DECK, false)
    renderPanel()
    switchTo('Preview')

    await screen.findByText('Could not render the preview')
    expect(screen.getByText('render crashed')).toBeTruthy()
  })
})
