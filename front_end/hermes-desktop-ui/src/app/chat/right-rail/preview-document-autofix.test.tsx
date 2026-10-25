import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createClientSessionState } from '@/lib/chat-runtime'
import { setDocFixSender } from '@/lib/harvis-doc-files'
import { clearLiveDocs, liveDocTarget, upsertLiveDoc } from '@/store/live-docs'
import { clearAllSessionStates, publishSessionState } from '@/store/session-states'
import { stubMenuDomApis, stubResizeObserver } from '@/test/jsdom'

import { DocumentPreview } from './preview-document'
import { $autoFixDocs, clearAutoFixed, DocCheckStrip } from './preview-document-check'

const DECK = '---\nkind: deck\ntitle: Q3 Review\n---\n# Q3 Review\n---\n## Threats\n- Phishing\n'
const ISSUES = [{ message: 'Title is cut off', severity: 'error', where: 'Slide 2' }]
const FIX = 'Fix these issues in the document:\n- Slide 2: Title is cut off'

const json = (body: unknown) => ({
  headers: new Headers(),
  json: async () => body,
  ok: true,
  status: 200,
  statusText: '200'
})

const answer = () => {
  const fetchMock = vi.fn(async () => json({ checked: { code: true, vision: false }, issues: ISSUES }))

  vi.stubGlobal('fetch', fetchMock)

  return fetchMock
}

const setBusy = (busy: boolean, interrupted = false) =>
  act(() => publishSessionState('rt-a', { ...createClientSessionState('chat-a'), busy, interrupted }))

const finish = (sessionId = 'chat-a', source = DECK) => (
  <DocCheckStrip complete kind="deck" sessionId={sessionId} source={source} title="Q3 Review" />
)

const streaming = (sessionId = 'chat-a', source = DECK) => (
  <DocCheckStrip complete={false} kind="deck" sessionId={sessionId} source={source} title="Q3 Review" />
)

describe('automatic document fix delivery', () => {
  beforeEach(() => {
    stubResizeObserver()
    stubMenuDomApis()
    clearLiveDocs()
    clearAllSessionStates()
    clearAutoFixed()
    $autoFixDocs.set(true)
  })

  afterEach(() => {
    cleanup()
    clearLiveDocs()
    clearAllSessionStates()
    clearAutoFixed()
    $autoFixDocs.set(false)
    setDocFixSender(null)
    vi.unstubAllGlobals()
  })

  it('does not call a refused send "Sent", and does not use up the automatic fix', async () => {
    const send = vi.fn(async () => false)

    answer()
    setDocFixSender(send)

    const view = render(streaming())

    view.rerender(finish())
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1))

    const button = (await screen.findByText('Fix it')).closest('button') as HTMLButtonElement

    expect(screen.queryByText('Sent')).toBeNull()
    expect(button.disabled).toBe(false)

    // The document is revised and finishes again: the automatic fix was not spent, so it retries.
    const revised = `${DECK}- more\n`

    view.rerender(streaming('chat-a', revised))
    view.rerender(finish('chat-a', revised))
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2))
  })

  it('does not call a manual Fix it that the chat refused "Sent"', async () => {
    const send = vi.fn(async () => false)

    answer()
    setDocFixSender(send)
    render(finish())

    fireEvent.click(screen.getByText('Check'))
    fireEvent.click(await screen.findByText('Fix it'))
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1))

    expect(screen.queryByText('Sent')).toBeNull()
    expect((screen.getByText('Fix it').closest('button') as HTMLButtonElement).disabled).toBe(false)
  })

  it('waits for the owning chat to go idle, then sends to that chat', async () => {
    const send = vi.fn(async () => true)

    answer()
    setDocFixSender(send)
    setBusy(true)

    const view = render(streaming())

    view.rerender(finish())
    await screen.findByText('Fix it')
    await new Promise(resolve => setTimeout(resolve, 30))

    // The model is still writing after the fence: nothing is sent, nothing is marked sent.
    expect(send).not.toHaveBeenCalled()
    expect(screen.queryByText('Sent')).toBeNull()

    setBusy(false)

    await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
    expect(send).toHaveBeenCalledWith(FIX, 'chat-a')
    await screen.findByText('Sent')
  })

  it('does not answer Stop with a new turn: the held fix is dropped, a later revision still gets it', async () => {
    const send = vi.fn(async () => true)

    answer()
    setDocFixSender(send)
    setBusy(true)

    const view = render(streaming())

    view.rerender(finish())
    await screen.findByText('Fix it')
    await new Promise(resolve => setTimeout(resolve, 30))
    expect(send).not.toHaveBeenCalled()

    // Stop: the turn ends, busy clears and the chat is marked interrupted.
    setBusy(false, true)
    await new Promise(resolve => setTimeout(resolve, 50))

    expect(send).not.toHaveBeenCalled()
    expect(screen.queryByText('Sent')).toBeNull()

    // The next turn clears the interrupt; its revised document gets the one automatic fix.
    const revised = `${DECK}- more\n`

    setBusy(true)
    setBusy(false)
    view.rerender(streaming('chat-a', revised))
    view.rerender(finish('chat-a', revised))
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
  })

  it('does not auto-send to a chat that was already stopped when the check finishes', async () => {
    const send = vi.fn(async () => true)

    answer()
    setDocFixSender(send)
    setBusy(false, true)

    const view = render(streaming())

    view.rerender(finish())
    await screen.findByText('Fix it')
    await new Promise(resolve => setTimeout(resolve, 50))

    expect(send).not.toHaveBeenCalled()
  })

  it('is not held up by a different chat that is busy', async () => {
    const send = vi.fn(async () => true)

    answer()
    setDocFixSender(send)
    act(() => publishSessionState('rt-b', { ...createClientSessionState('chat-b'), busy: true }))
    setBusy(false)

    const view = render(streaming())

    view.rerender(finish())
    await waitFor(() => expect(send).toHaveBeenCalledWith(FIX, 'chat-a'))
  })
})

describe('a document cut off by Stop', () => {
  const KEY = 'chat-a:q3-review'

  beforeEach(() => {
    stubResizeObserver()
    stubMenuDomApis()
    clearLiveDocs()
    clearAllSessionStates()
    clearAutoFixed()
    $autoFixDocs.set(true)
  })

  afterEach(() => {
    cleanup()
    clearLiveDocs()
    clearAllSessionStates()
    clearAutoFixed()
    $autoFixDocs.set(false)
    setDocFixSender(null)
    vi.unstubAllGlobals()
  })

  it('is neither checked nor auto-fixed, but can still be checked by hand', async () => {
    const send = vi.fn(async () => true)
    const fetchMock = answer()

    setDocFixSender(send)
    act(() => upsertLiveDoc(KEY, 'chat-a', DECK, true))
    render(<DocumentPreview target={liveDocTarget(KEY, 'Q3 Review')} />)

    // Stop: the card reports the fence no longer streaming, and not closed.
    act(() => upsertLiveDoc(KEY, 'chat-a', DECK, false, true))
    await new Promise(resolve => setTimeout(resolve, 50))

    expect(fetchMock).not.toHaveBeenCalled()
    expect(send).not.toHaveBeenCalled()

    const check = screen.getByText('Check').closest('button') as HTMLButtonElement

    expect(check.disabled).toBe(false)
    fireEvent.click(check)
    await screen.findByText('Fix it')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(send).not.toHaveBeenCalled()
  })

  it('still checks and fixes a fence that really closed', async () => {
    const send = vi.fn(async () => true)

    answer()
    setDocFixSender(send)
    act(() => upsertLiveDoc(KEY, 'chat-a', DECK, true))
    render(<DocumentPreview target={liveDocTarget(KEY, 'Q3 Review')} />)
    act(() => upsertLiveDoc(KEY, 'chat-a', DECK, false, false))

    await waitFor(() => expect(send).toHaveBeenCalledWith(FIX, 'chat-a'))
  })
})
