import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { resetServerCapabilities, setServerCapabilities } from '@/store/server-capabilities'

import { SidebarFilterMenu } from './filter-menu'

// Pretend a PR-capable git bridge exists, so only the capability flags decide.
vi.mock('@/lib/desktop-git', () => ({ desktopGit: () => ({ review: { prList: vi.fn() } }) }))

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.hasPointerCapture = vi.fn(() => false)
  Element.prototype.releasePointerCapture = vi.fn()
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  )
})

afterEach(() => {
  cleanup()
  resetServerCapabilities()
})

async function openMenu() {
  render(<SidebarFilterMenu />)

  const trigger = screen.getByRole('button', { name: 'Filters' })
  fireEvent.pointerDown(trigger, { button: 0, pointerType: 'mouse' })
  fireEvent.pointerUp(trigger, { button: 0, pointerType: 'mouse' })
  fireEvent.click(trigger)
  await screen.findByRole('menu')
}

describe('SidebarFilterMenu capability gating', () => {
  it('drops the Pull request filter when the server has no git remote', async () => {
    setServerCapabilities({ capabilities: { git_remote: false, projects: true } })
    await openMenu()

    expect(screen.getByText('Status')).toBeTruthy()
    expect(screen.queryByText('Pull request')).toBeNull()
  })

  it('keeps the Pull request filter when the server reaches a remote', async () => {
    setServerCapabilities({ capabilities: { git_remote: true, projects: true } })
    await openMenu()

    expect(screen.getByText('Pull request')).toBeTruthy()
  })
})
