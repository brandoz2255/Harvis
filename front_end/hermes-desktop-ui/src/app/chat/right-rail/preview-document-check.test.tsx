import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { docFixMessage, setDocFixSender } from '@/lib/harvis-doc-files'
import { createClientSessionState } from '@/lib/chat-runtime'
import { clearLiveDocs, liveDocTarget, upsertLiveDoc } from '@/store/live-docs'
import { clearAllSessionStates, publishSessionState } from '@/store/session-states'
import { stubMenuDomApis, stubResizeObserver } from '@/test/jsdom'

import { DocumentPreview } from './preview-document'
import { $autoFixDocs, clearAutoFixed, DocCheckStrip } from './preview-document-check'

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
  render(<DocCheckStrip complete kind="deck" sessionId="s1" source={DECK} title="Q3 Review" {...props} />)

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

  it('sends the errors back to the chat as a revision request', async () => {
    const send = vi.fn()

    setDocFixSender(send)
    answer({ checked: { code: true, vision: false }, issues: ISSUES })

    strip()
    fireEvent.click(screen.getByText('Check'))
    fireEvent.click(await screen.findByText('Fix it'))

    expect(send).toHaveBeenCalledWith(
      ['Fix these issues in the document:', '- Slide 2: Title is cut off at the right edge'].join('\n'),
      's1'
    )
    expect(send.mock.calls[0][0]).toBe(docFixMessage(ISSUES.slice(0, 1) as never))
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

    rerender(<DocCheckStrip complete kind="deck" sessionId="s1" source={`${DECK}- more\n`} title="Q3 Review" />)

    expect(screen.queryByText('Slide 4')).toBeNull()
  })
})

describe('DocCheckStrip automatic check and fix', () => {
  const calls = (fetchMock: ReturnType<typeof answer>) => fetchMock.mock.calls.length

  const body = (fetchMock: ReturnType<typeof answer>, n = 0) =>
    JSON.parse((fetchMock.mock.calls[n] as unknown as [string, RequestInit])[1].body as string)

  beforeEach(() => {
    setDocFixSender(null)
    clearAutoFixed()
    $autoFixDocs.set(false)
  })

  afterEach(() => {
    cleanup()
    setDocFixSender(null)
    clearAutoFixed()
    $autoFixDocs.set(false)
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  const partial = (source: string) => ({ complete: false, source })

  it('checks once when the document finishes, not on every stream chunk', async () => {
    const fetchMock = answer({ checked: { code: true, vision: false }, issues: [] })
    const { rerender } = strip(partial('---\nkind: deck\n---\n# A'))

    for (const chunk of ['# A\n---\n## B', '# A\n---\n## B\n- x', '# A\n---\n## B\n- x\n- y']) {
      rerender(<DocCheckStrip complete={false} kind="deck" sessionId="s1" source={chunk} title="Q3 Review" />)
    }

    expect(calls(fetchMock)).toBe(0)

    rerender(<DocCheckStrip complete kind="deck" sessionId="s1" source={DECK} title="Q3 Review" />)
    await screen.findByText('No problems found')
    expect(calls(fetchMock)).toBe(1)
    expect(body(fetchMock)).toMatchObject({ format: 'pptx', source: DECK, title: 'Q3 Review' })

    // An edit after it finished clears the result but does not start another check.
    rerender(<DocCheckStrip complete kind="deck" sessionId="s1" source={`${DECK}- more\n`} title="Q3 Review" />)
    expect(screen.queryByText('No problems found')).toBeNull()
    expect(calls(fetchMock)).toBe(1)
  })

  it('leaves a document that was already complete when the panel opened to the Check button', () => {
    const fetchMock = answer({ checked: { code: true, vision: false }, issues: [] })

    strip()

    expect(calls(fetchMock)).toBe(0)
  })

  it('respects the vision checkbox on the automatic check', async () => {
    const fetchMock = answer({ checked: { code: true, model: 'gemma3:4b', vision: true }, issues: [] })
    const { rerender } = strip(partial(DECK))

    fireEvent.click(screen.getByLabelText('Also look at the pages (slower)'))
    rerender(<DocCheckStrip complete kind="deck" sessionId="s1" source={DECK} title="Q3 Review" />)

    await screen.findByText('No problems found')
    expect(body(fetchMock).vision).toBe(true)
  })

  it('shows the findings on its own and offers Fix it with the issue count', async () => {
    const send = vi.fn()

    setDocFixSender(send)
    answer({ checked: { code: true, vision: false }, issues: ISSUES })

    const { rerender } = strip(partial(DECK))

    rerender(<DocCheckStrip complete kind="deck" sessionId="s1" source={DECK} title="Q3 Review" />)

    const fix = (await screen.findByText('Fix it')).closest('button') as HTMLButtonElement

    // Only the error counts: the warnings are listed but are not sent back.
    expect(fix.textContent).toBe('Fix it(1)')
    expect(send).not.toHaveBeenCalled()

    fireEvent.click(fix)
    expect(send).toHaveBeenCalledWith(docFixMessage(ISSUES.slice(0, 1) as never), 's1')
    expect(send.mock.calls[0][0].startsWith('Fix these issues in the document:')).toBe(true)
  })

  it('does not send anything by itself while the setting is off', async () => {
    const send = vi.fn()

    setDocFixSender(send)
    answer({ checked: { code: true, vision: false }, issues: ISSUES })

    const { rerender } = strip(partial(DECK))

    rerender(<DocCheckStrip complete kind="deck" sessionId="s1" source={DECK} title="Q3 Review" />)
    await screen.findByText('Fix it')

    expect(send).not.toHaveBeenCalled()
  })

  it('sends the errors once, and only once per document, when the setting is on', async () => {
    const send = vi.fn()
    const fetchMock = answer({ checked: { code: true, vision: false }, issues: ISSUES })

    $autoFixDocs.set(true)
    setDocFixSender(send)

    const { rerender } = strip(partial(DECK))

    rerender(<DocCheckStrip complete kind="deck" sessionId="s1" source={DECK} title="Q3 Review" />)
    await screen.findByText('Sent')

    expect(send).toHaveBeenCalledTimes(1)
    expect(send).toHaveBeenCalledWith(
      'Fix these issues in the document:\n- Slide 2: Title is cut off at the right edge',
      's1'
    )

    // The revision streams in and still fails its check: it is checked, not fixed again.
    const revised = `${DECK}- revised\n`

    rerender(<DocCheckStrip complete={false} kind="deck" sessionId="s1" source={revised} title="Q3 Review" />)
    rerender(<DocCheckStrip complete kind="deck" sessionId="s1" source={revised} title="Q3 Review" />)
    await waitFor(() => expect(calls(fetchMock)).toBe(2))
    await screen.findByText('Slide 4')

    expect(send).toHaveBeenCalledTimes(1)
  })

  it('does not auto-send warnings or send without a registered sender', async () => {
    const send = vi.fn()

    $autoFixDocs.set(true)
    answer({ checked: { code: true, vision: false }, issues: ISSUES.slice(1) })
    setDocFixSender(send)

    const first = strip(partial(DECK))

    first.rerender(<DocCheckStrip complete kind="deck" sessionId="s1" source={DECK} title="Q3 Review" />)
    await screen.findByText('Slide 4')
    expect(send).not.toHaveBeenCalled()
    cleanup()

    setDocFixSender(null)
    answer({ checked: { code: true, vision: false }, issues: ISSUES })

    const second = strip(partial(DECK))

    second.rerender(<DocCheckStrip complete kind="deck" sessionId="s1" source={DECK} title="Q3 Review" />)
    await screen.findByText('Slide 4')
    expect(send).not.toHaveBeenCalled()
  })
})

describe('DocCheckStrip fix button and auto-fix scope', () => {
  const body = (fetchMock: ReturnType<typeof answer>, n = 0) =>
    JSON.parse((fetchMock.mock.calls[n] as unknown as [string, RequestInit])[1].body as string)

  beforeEach(() => {
    setDocFixSender(null)
    clearAutoFixed()
    $autoFixDocs.set(false)
  })

  afterEach(() => {
    cleanup()
    setDocFixSender(null)
    clearAutoFixed()
    $autoFixDocs.set(false)
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('offers no Fix it button when the check found only warnings', async () => {
    setDocFixSender(vi.fn())
    answer({ checked: { code: true, vision: false }, issues: ISSUES.slice(1) })

    strip()
    fireEvent.click(screen.getByText('Check'))

    await screen.findByText('Slide 4')
    expect(screen.queryByText('Fix it')).toBeNull()
  })

  it('sends the errors only from the button, not the warnings next to them', async () => {
    const send = vi.fn()

    setDocFixSender(send)
    answer({ checked: { code: true, vision: false }, issues: ISSUES })

    strip()
    fireEvent.click(screen.getByText('Check'))
    fireEvent.click(await screen.findByText('Fix it'))

    await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
    expect(send).toHaveBeenCalledWith(
      'Fix these issues in the document:\n- Slide 2: Title is cut off at the right edge',
      's1'
    )
  })

  it('gives a same-named document in another chat its own automatic fix', async () => {
    const send = vi.fn()

    $autoFixDocs.set(true)
    setDocFixSender(send)
    answer({ checked: { code: true, vision: false }, issues: ISSUES })

    for (const sessionId of ['chat-a', 'chat-b']) {
      const view = strip({ complete: false, sessionId })

      view.rerender(<DocCheckStrip complete kind="deck" sessionId={sessionId} source={DECK} title="Q3 Review" />)
      await waitFor(() => expect(send).toHaveBeenCalledTimes(sessionId === 'chat-a' ? 1 : 2))
      cleanup()
    }
  })

  it('waits for the real end of the stream before the automatic check, not just a stalled card', async () => {
    const fetchMock = answer({ checked: { code: true, vision: false }, issues: [] })
    const view = strip({ complete: false })

    // The 30 s fallback calls the document complete while the turn is still running.
    view.rerender(<DocCheckStrip complete kind="deck" sessionId="s1" settled={false} source={DECK} title="Q3 Review" />)
    expect(fetchMock).not.toHaveBeenCalled()

    view.rerender(<DocCheckStrip complete kind="deck" sessionId="s1" settled source={DECK} title="Q3 Review" />)
    await screen.findByText('No problems found')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(body(fetchMock).source).toBe(DECK)
  })

  it('has a checkbox for the automatic fix that flips the setting', () => {
    strip()

    const box = screen.getByLabelText('Fix errors automatically') as HTMLInputElement

    expect(box.checked).toBe(false)
    fireEvent.click(box)
    expect($autoFixDocs.get()).toBe(true)
    expect(box.checked).toBe(true)
  })
})

describe('DocCheckStrip in the panel when the card stalls mid-stream', () => {
  const KEY = 'session-stall:q3-review'

  beforeEach(() => {
    stubResizeObserver()
    stubMenuDomApis()
    clearLiveDocs()
    clearAllSessionStates()
    clearAutoFixed()
    $autoFixDocs.set(false)
  })

  afterEach(() => {
    cleanup()
    clearLiveDocs()
    clearAllSessionStates()
    clearAutoFixed()
    $autoFixDocs.set(false)
    setDocFixSender(null)
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('checks the finished document once, not the partial one a stalled card left behind', async () => {
    const PARTIAL = DECK.slice(0, DECK.indexOf('## Threats') + 6)
    const FULL = `${DECK}---\n## Controls\n- MFA\n`
    const send = vi.fn()
    const fetchMock = vi.fn(async () => json({ checked: { code: true, vision: false }, issues: ISSUES }))

    $autoFixDocs.set(true)
    setDocFixSender(send)
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers({ toFake: ['clearInterval', 'Date', 'setInterval'] })
    publishSessionState('rt-stall', { ...createClientSessionState('session-stall'), busy: true })
    act(() => upsertLiveDoc(KEY, 'session-stall', PARTIAL, true))
    render(<DocumentPreview target={liveDocTarget(KEY, 'Q3 Review')} />)

    // The card scrolled out of the transcript: no update for longer than the staleness window.
    act(() => {
      vi.advanceTimersByTime(40_000)
    })

    expect(screen.getByText('Done')).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()

    // The turn ends but the card never reported the fence closing: its source is still partial,
    // so nothing may be checked or sent to whichever chat is open.
    vi.useRealTimers()
    act(() => publishSessionState('rt-stall', { ...createClientSessionState('session-stall'), busy: false }))
    await new Promise(resolve => setTimeout(resolve, 50))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(send).not.toHaveBeenCalled()

    // The card remounts and reports the full source: that is the one automatic check.
    act(() => upsertLiveDoc(KEY, 'session-stall', FULL, false))

    await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string).source).toBe(FULL)
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

  it('is only usable once the document has finished', async () => {
    act(() => upsertLiveDoc(KEY, 'session-check', DECK, true))
    render(<DocumentPreview target={liveDocTarget(KEY, 'Q3 Review')} />)

    const check = () => screen.getByText('Check').closest('button') as HTMLButtonElement

    expect(check().disabled).toBe(true)

    vi.stubGlobal('fetch', vi.fn(async () => json({ checked: { code: true, vision: false }, issues: [] })))
    act(() => upsertLiveDoc(KEY, 'session-check', DECK, false))

    // Finishing starts the one automatic check; once it has answered the button is usable again.
    await screen.findByText('No problems found')
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
        'Fix these issues in the document:\n- Slide 2: Title is cut off at the right edge',
        'session-check'
      )
    )
    setDocFixSender(null)
  })
})
