import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { atom } from 'nanostores'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { $notifications, clearNotifications } from '@/store/notifications'
import { resetServerCapabilities, setServerCapabilities } from '@/store/server-capabilities'

vi.mock('@/store/coding-status', () => ({
  registerRepoStatusCwd: () => undefined,
  repoStatusForCwd: () =>
    atom({
      added: 12,
      ahead: 0,
      behind: 0,
      branch: 'bb/hitbox',
      defaultBranch: 'main',
      detached: false,
      removed: 3,
      untracked: 0
    }),
  repoWorktreesForCwd: () => atom([])
}))

const { CodingStatusRow } = await import('./coding-row')

describe('CodingStatusRow', () => {
  afterEach(() => {
    cleanup()
    resetServerCapabilities()
  })

  it('opens the review pane from the branch and the diff counts, never the bar itself', () => {
    const onOpen = vi.fn()

    const { container } = render(<CodingStatusRow onOpen={onOpen} repoPath="/repo" />)

    const bar = container.querySelector<HTMLElement>('.coding-status-bar')

    expect(bar).not.toBeNull()

    fireEvent.click(bar!)
    expect(onOpen).not.toHaveBeenCalled()

    fireEvent.click(screen.getByText('bb/hitbox'))
    expect(onOpen).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByText('12'))
    expect(onOpen).toHaveBeenCalledTimes(2)
  })

  it('wraps the click targets without adding a layout box', () => {
    const { container } = render(<CodingStatusRow onOpen={() => undefined} repoPath="/repo" />)

    // `display: contents` is what keeps the branch label and the counts direct
    // flex children of the row — the hit areas cost nothing visually.
    expect(screen.getByText('bb/hitbox').parentElement?.classList.contains('contents')).toBe(true)
    expect(screen.getByText('12').closest('button')?.classList.contains('contents')).toBe(true)
    // The glyph button fills the row's existing 3.5 leading slot exactly.
    expect(container.querySelector('button[class~="size-3.5"]')).not.toBeNull()
  })

  it('parks the copy glyph against the end of the path, not the end of the row', () => {
    render(<CodingStatusRow onOpen={() => undefined} repoPath="/Users/someone/www/repo" />)

    const path = screen.getByText('~/www/repo')

    // The path sizes to its content and the glyph is its immediate sibling, so
    // the pair reads as one unit. `flex-1` belongs to the wrapper (which holds
    // the row's slack open) — on the label it stretched the text and pushed the
    // glyph out to the kebab.
    expect(path.classList.contains('flex-1')).toBe(false)
    expect(path.parentElement?.classList.contains('flex-1')).toBe(true)
    expect(path.nextElementSibling?.tagName).toBe('BUTTON')
  })

  it('copies the absolute cwd inline — checkmark feedback, no toast', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    clearNotifications()

    render(<CodingStatusRow onOpen={() => undefined} repoPath="/Users/someone/www/repo" />)

    // Painted tildified, copied raw.
    expect(screen.getByText('~/www/repo')).toBeTruthy()

    const copy = screen.getByRole('button', { name: 'Copy path' })

    fireEvent.click(copy)

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('/Users/someone/www/repo'))
    // Confirmation is the button turning into a checkmark, not a notification.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copied' })).toBeTruthy())
    expect($notifications.get()).toHaveLength(0)
  })

  describe('branch menu on a Harvis sandbox', () => {
    const branchOff = async () => undefined
    const switchBranch = async () => undefined

    it('offers no menu when the backend cannot add worktrees and there is nothing to switch to', () => {
      setServerCapabilities({ capabilities: { git: true, git_worktrees: false } })
      render(<CodingStatusRow onBranchOff={branchOff} onOpen={() => undefined} repoPath="/repo" />)

      expect(screen.queryByLabelText('New branch')).toBeNull()
    })

    it('keeps the menu for switching branches, without the worktree entries', async () => {
      setServerCapabilities({ capabilities: { git: true, git_worktrees: false } })
      render(
        <CodingStatusRow
          onBranchOff={branchOff}
          onOpen={() => undefined}
          onSwitchBranch={switchBranch}
          repoPath="/repo"
        />
      )

      fireEvent.pointerDown(screen.getByLabelText('New branch'), { button: 0, ctrlKey: false })
      fireEvent.click(screen.getByLabelText('New branch'))

      await waitFor(() => expect(screen.getByText('Switch to main')).toBeTruthy())
      expect(screen.queryByText('Worktrees')).toBeNull()
    })

    it('shows the full menu once worktrees are provided', () => {
      setServerCapabilities({ capabilities: { git: true, git_worktrees: true } })
      render(<CodingStatusRow onBranchOff={branchOff} onOpen={() => undefined} repoPath="/repo" />)

      expect(screen.getByLabelText('New branch')).toBeTruthy()
    })
  })
})
