import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChatMessage } from '@/lib/chat-messages'
import {
  $activeSessionId,
  $busy,
  $currentUsage,
  $messages,
  $selectedStoredSessionId,
  $workspaceCwdOwner,
  setCurrentCwd,
  setCurrentModel,
  setCurrentProvider
} from '@/store/session'

import { sessionChangedFiles } from './session-changes'
import { SessionPanel } from './session-panel'
import { setSessionPanelCollapsed } from './store'

const requestGateway = vi.fn()

vi.mock('@/app/gateway/hooks/use-gateway-request', () => ({
  useGatewayRequest: () => ({ requestGateway })
}))

const toolCall = (
  toolName: string,
  args: Record<string, unknown>,
  extra: { isError?: boolean; result?: unknown } = { result: 'ok' }
): ChatMessage['parts'][number] =>
  ({
    args,
    argsText: JSON.stringify(args),
    toolCallId: `${toolName}-${JSON.stringify(args)}`,
    toolName,
    type: 'tool-call',
    ...extra
  }) as ChatMessage['parts'][number]

const assistant = (...parts: ChatMessage['parts']): ChatMessage => ({ id: 'a1', parts, role: 'assistant' })

function reset() {
  $messages.set([])
  $busy.set(false)
  $activeSessionId.set(null)
  $selectedStoredSessionId.set(null)
  $workspaceCwdOwner.set(null)
  $currentUsage.set({ calls: 0, input: 0, output: 0, total: 0 })
  setCurrentModel('')
  setCurrentProvider('')
  setCurrentCwd('')
  setSessionPanelCollapsed(false)
  requestGateway.mockReset()
  requestGateway.mockRejectedValue(new Error('no gateway'))
}

describe('sessionChangedFiles', () => {
  it('lists finished write/edit/patch calls newest first, resolved against the sandbox folder', () => {
    const files = sessionChangedFiles(
      [
        assistant(
          toolCall('write_file', { path: 'a.txt' }),
          toolCall('read_file', { path: 'ignored.txt' }),
          toolCall('edit_file', { file_path: '/sandbox/c/workspace/src/b.ts' }),
          toolCall('write_file', { path: './a.txt' })
        )
      ],
      '/sandbox/c/workspace'
    )

    expect(files).toEqual([
      { label: 'a.txt', path: '/sandbox/c/workspace/a.txt' },
      { label: 'src/b.ts', path: '/sandbox/c/workspace/src/b.ts' }
    ])
  })

  it('skips calls that are still running or that failed', () => {
    const files = sessionChangedFiles(
      [
        assistant(
          toolCall('write_file', { path: 'running.txt' }, {}),
          toolCall('write_file', { path: 'failed.txt' }, { isError: true, result: 'boom' }),
          toolCall('write_file', { path: 'soft-fail.txt' }, { result: JSON.stringify({ error: 'denied' }) }),
          toolCall('write_file', { path: 'good.txt' })
        )
      ],
      '/w'
    )

    expect(files.map(file => file.label)).toEqual(['good.txt'])
  })

  it('counts the Harvis workspace edit tools', () => {
    const files = sessionChangedFiles(
      [
        assistant(
          toolCall('str_replace', { path: 'src/x.ts', old_str: 'a', new_str: 'b' }),
          toolCall('apply_patch', { path: 'notes.md', content: 'hi' })
        )
      ],
      '/w'
    )

    expect(files.map(file => file.label)).toEqual(['notes.md', 'src/x.ts'])
  })

  it('reads every file named in a patch body', () => {
    const patch = '*** Begin Patch\n*** Update File: one.py\n@@\n-a\n+b\n*** Add File: dir/two.py\n+x\n*** End Patch'

    expect(sessionChangedFiles([assistant(toolCall('patch', { patch }))], '/w').map(file => file.path)).toEqual([
      '/w/dir/two.py',
      '/w/one.py'
    ])
  })
})

describe('SessionPanel', () => {
  beforeEach(reset)

  afterEach(() => {
    cleanup()
    reset()
  })

  it('shows the model, provider and sandbox folder', () => {
    setCurrentModel('claude-sonnet-5-5')
    setCurrentProvider('anthropic')
    $selectedStoredSessionId.set('s1')
    $workspaceCwdOwner.set('s1')
    setCurrentCwd('/sandbox/chat-7/workspace')

    render(<SessionPanel onActivateFile={vi.fn()} />)

    expect(screen.getByText('claude-sonnet-5-5 · anthropic')).toBeTruthy()
    expect(screen.getByText('…/chat-7/workspace')).toBeTruthy()
  })

  it('does not claim a retained folder that belongs to another conversation', () => {
    $selectedStoredSessionId.set('new')
    $workspaceCwdOwner.set('old')
    setCurrentCwd('/sandbox/old/workspace')

    render(<SessionPanel onActivateFile={vi.fn()} />)

    expect(screen.queryByText(/old\/workspace/)).toBeNull()
    expect(screen.getByText('Created with your first message')).toBeTruthy()
  })

  it('draws the context bar from the streamed usage', () => {
    $currentUsage.set({
      calls: 1,
      context_max: 200000,
      context_percent: 42,
      context_used: 84000,
      input: 1,
      output: 1,
      total: 2
    })

    render(<SessionPanel onActivateFile={vi.fn()} />)

    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('42')
    expect(screen.getByText('42% full')).toBeTruthy()
    expect(screen.getByText('~84k of 200k tokens')).toBeTruthy()
  })

  it('prefers the measured breakdown over stale usage', async () => {
    $activeSessionId.set('rt1')
    $currentUsage.set({
      calls: 1,
      context_max: 200000,
      context_percent: 90,
      context_used: 180000,
      input: 1,
      output: 1,
      total: 2
    })
    requestGateway.mockResolvedValue({ categories: [], context_max: 1000, context_percent: 10, context_used: 100 })

    render(<SessionPanel onActivateFile={vi.fn()} />)

    await waitFor(() => expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('10'))
    expect(requestGateway).toHaveBeenCalledWith('session.context_breakdown', { session_id: 'rt1' })
  })

  it('says so when context is not measured yet', () => {
    render(<SessionPanel onActivateFile={vi.fn()} />)

    expect(screen.getByText('Not measured yet')).toBeTruthy()
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('says "No changes yet" when nothing was written', () => {
    render(<SessionPanel onActivateFile={vi.fn()} />)

    expect(screen.getByText('No changes yet')).toBeTruthy()
  })

  it('lists changed files, caps at eight, and opens one on click', () => {
    $selectedStoredSessionId.set('s1')
    $workspaceCwdOwner.set('s1')
    setCurrentCwd('/w')
    $messages.set([assistant(...Array.from({ length: 10 }, (_, i) => toolCall('write_file', { path: `f${i}.txt` })))])

    const onActivateFile = vi.fn()

    render(<SessionPanel onActivateFile={onActivateFile} />)

    expect(screen.getAllByRole('button', { name: /^Open f/ })).toHaveLength(8)
    expect(screen.getByText('+2 more')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Open f9.txt' }))
    expect(onActivateFile).toHaveBeenCalledWith('/w/f9.txt')
  })

  it('collapses, remembers it, and stops fetching context while folded', () => {
    render(<SessionPanel onActivateFile={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Hide session details' }))

    expect(screen.queryByText('No changes yet')).toBeNull()
    expect(window.localStorage.getItem('hermes.desktop.rightSidebar.sessionPanelCollapsed')).toBe('true')

    fireEvent.click(screen.getByRole('button', { name: 'Show session details' }))
    expect(screen.getByText('No changes yet')).toBeTruthy()
  })
})
