import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetServerCapabilities, setServerCapabilities } from '@/store/server-capabilities'

import { useComposerBranch } from './use-composer-branch'

const startWorkInRepo = vi.fn()
const switchBranchInRepo = vi.fn()
const requestStartWorkSession = vi.fn()

vi.mock('@/store/projects', () => ({
  listRepoBranches: vi.fn(),
  requestStartWorkSession: (...args: unknown[]) => requestStartWorkSession(...args),
  startWorkInRepo: (...args: unknown[]) => startWorkInRepo(...args),
  switchBranchInRepo: (...args: unknown[]) => switchBranchInRepo(...args)
}))
vi.mock('../scope', () => ({ useComposerScope: () => ({ attachments: { clear: vi.fn() } }) }))

const setup = () =>
  renderHook(() => useComposerBranch({ clearDraft: vi.fn(), cwd: '/repo', draftRef: { current: 'draft' } })).result
    .current

describe('useComposerBranch capability gating', () => {
  beforeEach(() => {
    startWorkInRepo.mockResolvedValue({ path: '/repo-wt' })
  })

  afterEach(() => {
    resetServerCapabilities()
    vi.clearAllMocks()
  })

  it('creates no worktree when the server has none', async () => {
    setServerCapabilities({ capabilities: { git: true, git_worktrees: false } })
    const branch = setup()

    await branch.handleBranchOff('feature')
    await branch.handleConvertBranch('feature')

    expect(startWorkInRepo).not.toHaveBeenCalled()
    expect(requestStartWorkSession).not.toHaveBeenCalled()
  })

  it('still switches branches in place without worktrees', async () => {
    setServerCapabilities({ capabilities: { git: true, git_worktrees: false } })

    await setup().handleSwitchBranch('main')

    expect(switchBranchInRepo).toHaveBeenCalledWith('/repo', 'main')
  })

  it('creates a worktree and opens a session in it when the server supports worktrees', async () => {
    setServerCapabilities({ capabilities: { git: true, git_worktrees: true } })

    await setup().handleBranchOff('feature')

    expect(startWorkInRepo).toHaveBeenCalledWith('/repo', { base: undefined, branch: 'feature', name: 'feature' })
    expect(requestStartWorkSession).toHaveBeenCalledWith('/repo-wt', 'draft')
  })
})
