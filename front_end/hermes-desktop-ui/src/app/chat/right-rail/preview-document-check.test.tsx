import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { docFixMessage, setDocFixSender } from '@/lib/harvis-doc-files'
import { clearLiveDocs, liveDocTarget, upsertLiveDoc } from '@/store/live-docs'
import { stubMenuDomApis, stubResizeObserver } from '@/test/jsdom'

import { DocumentPreview } from './preview-document'
import { DocCheckStrip } from './preview-document-check'

const CHECK_URL = '/hermes-api/api/harvis/docs/check'
const DECK = '---\nkind: deck\ntitle: Q3 Review\n---\n# Q3 Review\n---\n## Threats\n- Phishing\n'

const json = (body: unknown, status = 200) => ({
  headers: new Headers(),
  json: async () => body,
  ok: status < 400,
  status,
  statusText: String(status)
})

const ISSUES = [
  { message: 'Title is cut off at the right edge', severity: 'error', where: 'Slide 2' },
  { message: 'Body text is very small', severity: 'warn', where: 'Slide 2' },
  { message: 'Image has no alt text', severity: 'warn', where: 'Slide 4' }
]

function answer(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () => json(body, status))

  vi.stubGlobal('fetch', fetchMock)

  return fetchMock
}

const strip = (props: Partial<React.ComponentProps<typeof DocCheckStrip>> = {}) =>
  render(<DocCheckStrip complete kind="deck" source={DECK} title="Q3 Review" {...props} />)

describe('DocCheckStrip', () => {
  beforeEach(() => {
    setDocFixSender(null)
  })

  afterEach(() => {
    cleanup()
    setDocFixSender(null)
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('stays disabled until the document is complete', () => {
    const fetchMock = answer({ checked: { code: true, vision: false }, issues: [] })

    strip({ complete: false })

    expect((screen.getByText('Check').closest('button') as HTMLButtonElement).disabled).toBe(true)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('posts the document, spins while checking, and lists issues grouped by where', async () => {
    const fetchMock = answer({ checked: { code: true, vision: false }, issues: ISSUES })

    strip()
    fireEvent.click(screen.getByText('Check'))

    expect(screen.getByText('Checking…')).toBeTruthy()

    await screen.findByText('Title is cut off at the right edge')

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]

    expect(url).toBe(CHECK_URL)
    expect(init.credentials).toBe('include')
    expect(JSON.parse(init.body as string)).toMatchObject({ format: 'pptx', source: DECK, title: 'Q3 Review' })

    const groups = Array.from(document.querySelectorAll('[data-slot="doc-check-results"] > ul > li'))

    expect(groups.map(g => g.firstElementChild?.textContent)).toEqual(['Slide 2', 'Slide 4'])
    expect(groups[0].querySelectorAll('[data-severity]')).toHaveLength(2)
    expect(groups[0].querySelector('[data-severity="error"] span')?.className).toContain('text-destructive')
    expect(groups[0].querySelector('[data-severity="warn"] span')?.className).toContain('text-amber')
    expect(screen.queryByText(/Checked by/)).toBeNull()
  })

  it('says so when nothing is wrong', async () => {
    answer({ checked: { code: true, vision: false }, issues: [] })

    strip()
    fireEvent.click(screen.getByText('Check'))

    await screen.findByText('No problems found')
    expect(screen.queryByText('Fix it')).toBeNull()
  })

  it('sends vision: false explicitly when the box is unticked', async () => {
    const fetchMock = answer({ checked: { code: true, vision: false }, issues: [] })

    strip()
    fireEvent.click(screen.getByText('Check'))

    await screen.findByText('No problems found')

    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)

    expect(body.vision).toBe(false)
  })

  it('asks for the vision pass when ticked and names the model that ran it', async () => {
    const fetchMock = answer({ checked: { code: true, model: 'gemma3:4b', vision: true }, issues: ISSUES })

    strip()
    fireEvent.click(screen.getByLabelText('Also look at the pages (slower)'))
    fireEvent.click(screen.getByText('Check'))

    await screen.findByText('Checked by gemma3:4b')
    expect(JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string).vision).toBe(
      true
    )
  })

  it('sends the issues back to the chat as a revision request', async () => {
    const send = vi.fn()

    setDocFixSender(send)
    answer({ checked: { code: true, vision: false }, issues: ISSUES })

    strip()
    fireEvent.click(screen.getByText('Check'))
    fireEvent.click(await screen.findByText('Fix it'))

    expect(send).toHaveBeenCalledWith(
      [
        'Fix these issues in the document:',
        '- Slide 2: Title is cut off at the right edge',
        '- Slide 2: Body text is very small',
        '- Slide 4: Image has no alt text'
      ].join('\n')
    )
    expect(send.mock.calls[0][0]).toBe(docFixMessage(ISSUES as never))
    await screen.findByText('Sent')
    expect((screen.getByText('Sent').closest('button') as HTMLButtonElement).disabled).toBe(true)
  })

  it('disables Fix it with a tooltip when the app has registered no way to send', async () => {
    answer({ checked: { code: true, vision: false }, issues: ISSUES })

    strip()
    fireEvent.click(screen.getByText('Check'))

    const fix = (await screen.findByText('Fix it')).closest('button') as HTMLButtonElement

    expect(fix.disabled).toBe(true)
    expect(fix.parentElement?.title).toBe('Sending to the chat is not available here')
  })

  it('shows a failed check without losing the button', async () => {
    answer({ detail: 'checker offline' }, 500)

    strip()
    fireEvent.click(screen.getByText('Check'))

    await screen.findByText('Check failed')
    expect(screen.getByText('Check')).toBeTruthy()
  })

  it('drops results that belong to an older version of the document', async () => {
    answer({ checked: { code: true, vision: false }, issues: ISSUES })

    const { rerender } = strip()

    fireEvent.click(screen.getByText('Check'))
    await screen.findByText('Slide 4')

    rerender(<DocCheckStrip complete kind="deck" source={`${DECK}- more\n`} title="Q3 Review" />)

    expect(screen.queryByText('Slide 4')).toBeNull()
  })
})

describe('DocCheckStrip inside the document panel', () => {
  const KEY = 'session-check:q3-review'

  beforeEach(() => {
    stubResizeObserver()
    stubMenuDomApis()
    clearLiveDocs()
  })

  afterEach(() => {
    cleanup()
    clearLiveDocs()
    vi.unstubAllGlobals()
  })

  it('is only usable once the document has finished', () => {
    act(() => upsertLiveDoc(KEY, 'session-check', DECK, true))
    render(<DocumentPreview target={liveDocTarget(KEY, 'Q3 Review')} />)

    const check = () => screen.getByText('Check').closest('button') as HTMLButtonElement

    expect(check().disabled).toBe(true)

    act(() => upsertLiveDoc(KEY, 'session-check', DECK, false))

    expect(check().disabled).toBe(false)
  })

  it('sends Fix it through the registered sender', async () => {
    const send = vi.fn()

    setDocFixSender(send)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json({ checked: { code: true, vision: false }, issues: ISSUES.slice(0, 1) }))
    )
    act(() => upsertLiveDoc(KEY, 'session-check', DECK, false))
    render(<DocumentPreview target={liveDocTarget(KEY, 'Q3 Review')} />)

    fireEvent.click(screen.getByText('Check'))
    fireEvent.click(await screen.findByText('Fix it'))

    await waitFor(() =>
      expect(send).toHaveBeenCalledWith(
        'Fix these issues in the document:\n- Slide 2: Title is cut off at the right edge'
      )
    )
    setDocFixSender(null)
  })
})
