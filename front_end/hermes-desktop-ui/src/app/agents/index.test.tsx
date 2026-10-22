// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n'
import { $subagentsBySession, type SubagentProgress } from '@/store/subagents'

const openSession = vi.fn()

vi.mock('../open-session', () => ({ openSession: (...args: unknown[]) => openSession(...args) }))

const { AgentsView } = await import('./index')

function agent(overrides: Partial<SubagentProgress>): SubagentProgress {
  return {
    filesRead: [],
    filesWritten: [],
    goal: 'Check the build',
    id: 'a',
    parentId: null,
    startedAt: 1,
    status: 'completed',
    stream: [],
    taskCount: 1,
    taskIndex: 0,
    updatedAt: 1,
    ...overrides
  }
}

function mount(onClose = vi.fn()) {
  render(
    <MemoryRouter>
      <I18nProvider>
        <AgentsView onClose={onClose} />
      </I18nProvider>
    </MemoryRouter>
  )

  return onClose
}

describe('AgentsView open action', () => {
  beforeEach(() => {
    openSession.mockClear()
    $subagentsBySession.set({})
    // jsdom has no Web Animations API; the row's enter animation calls it.
    Object.defineProperty(HTMLElement.prototype, 'animate', {
      configurable: true,
      value: () => ({}) as Animation,
      writable: true
    })
  })

  afterEach(() => {
    cleanup()
    Reflect.deleteProperty(HTMLElement.prototype, 'animate')
    $subagentsBySession.set({})
  })

  it('opens a finished step as a stored-session tab and closes the panel', () => {
    act(() => $subagentsBySession.set({ s: [agent({ sessionId: 'child-1' })] }))
    const onClose = mount()

    fireEvent.click(screen.getByRole('button', { name: /^Open/ }))

    expect(openSession).toHaveBeenCalledWith('child-1', expect.any(Function), 'tab')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('offers it for failed steps too', () => {
    act(() => $subagentsBySession.set({ s: [agent({ sessionId: 'child-2', status: 'failed' })] }))
    mount()

    expect(screen.getByRole('button', { name: /^Open/ })).toBeTruthy()
  })

  it('hides it while running or when no child session was stored', () => {
    act(() =>
      $subagentsBySession.set({
        s: [
          agent({ id: 'r', sessionId: 'child-3', status: 'running' }),
          agent({ id: 'n', goal: 'No session', status: 'completed' })
        ]
      })
    )
    mount()

    expect(screen.queryByRole('button', { name: /^Open/ })).toBeNull()
  })
})
