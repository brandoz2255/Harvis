import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { $docFixSender } from '@/lib/harvis-doc-files'
import { $followupsBySession, setSessionFollowups, startFollowup } from '@/store/followups'

import { useFollowupBridge } from './use-followup-bridge'

function Bridge(props: Parameters<typeof useFollowupBridge>[0]) {
  useFollowupBridge(props)

  return null
}

describe('useFollowupBridge', () => {
  afterEach(() => {
    cleanup()
    $followupsBySession.set({})
  })

  it('starts a fresh draft, then submits the prompt through the normal pipeline', async () => {
    const order: string[] = []
    const startFreshSessionDraft = vi.fn(() => void order.push('fresh'))

    const submitText = vi.fn(async (text: string) => {
      order.push(`submit:${text}`)
    })

    render(<Bridge startFreshSessionDraft={startFreshSessionDraft} submitText={submitText} />)
    setSessionFollowups('s1', [{ prompt: 'Ship it', title: 'Ship' }])

    expect(startFollowup('s1', { prompt: 'Ship it', title: 'Ship' })).toBe(true)
    await Promise.resolve()

    expect(order).toEqual(['fresh', 'submit:Ship it'])
  })

  it('unregisters on unmount so a stale click cannot reach a dead window', () => {
    const { unmount } = render(<Bridge startFreshSessionDraft={vi.fn()} submitText={vi.fn()} />)
    unmount()

    expect(startFollowup('s1', { prompt: 'p', title: 't' })).toBe(false)
  })

  it('follows the latest callbacks without re-registering', async () => {
    const first = vi.fn()
    const second = vi.fn()

    const { rerender } = render(<Bridge startFreshSessionDraft={vi.fn()} submitText={first} />)
    rerender(<Bridge startFreshSessionDraft={vi.fn()} submitText={second} />)

    startFollowup('s1', { prompt: 'go', title: 't' })
    await Promise.resolve()

    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledWith('go')
  })

  it('registers the document Fix it sender into the current chat, no fresh draft', async () => {
    const startFreshSessionDraft = vi.fn()
    const submitText = vi.fn()
    const { unmount } = render(<Bridge startFreshSessionDraft={startFreshSessionDraft} submitText={submitText} />)

    await $docFixSender.get()?.('Fix these issues in the document:\n- slide 2: x')

    expect(submitText).toHaveBeenCalledWith('Fix these issues in the document:\n- slide 2: x')
    expect(startFreshSessionDraft).not.toHaveBeenCalled()
    unmount()
    expect($docFixSender.get()).toBeNull()
  })
})
