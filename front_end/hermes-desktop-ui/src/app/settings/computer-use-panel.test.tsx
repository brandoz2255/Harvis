import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetServerCapabilities, setServerCapabilities } from '@/store/server-capabilities'

import { ComputerUsePanel } from './computer-use-panel'

const getComputerUseStatus = vi.fn()

vi.mock('@/hermes', () => ({
  getActionStatus: vi.fn(),
  getComputerUseStatus: () => getComputerUseStatus(),
  grantComputerUsePermissions: vi.fn()
}))
vi.mock('@/store/activity', () => ({ upsertDesktopActionTask: vi.fn() }))
vi.mock('@/store/notifications', () => ({ notify: vi.fn(), notifyError: vi.fn() }))

afterEach(() => {
  cleanup()
  resetServerCapabilities()
  vi.clearAllMocks()
})

describe('ComputerUsePanel', () => {
  it('renders nothing and reads no status when the server reports computer_use_grant off', () => {
    setServerCapabilities({ capabilities: { computer_use_grant: false } })

    const { container } = render(<ComputerUsePanel />)

    expect(container.textContent).toBe('')
    expect(getComputerUseStatus).not.toHaveBeenCalled()
  })

  it('checks status when the server can grant', () => {
    getComputerUseStatus.mockReturnValue(new Promise(() => undefined))
    setServerCapabilities({ capabilities: { computer_use_grant: true } })

    render(<ComputerUsePanel />)

    expect(screen.getByText(/Checking Computer Use status/)).toBeTruthy()
    expect(getComputerUseStatus).toHaveBeenCalledTimes(1)
  })
})
