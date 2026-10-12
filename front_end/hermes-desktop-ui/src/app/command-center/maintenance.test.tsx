import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type * as HermesApi from '@/hermes'
import { resetServerCapabilities, setServerCapabilities } from '@/store/server-capabilities'

import { MaintenancePanel } from './maintenance'

const mocks = vi.hoisted(() => ({
  getCuratorStatus: vi.fn(() => Promise.resolve({ enabled: true, paused: false, last_run_at: null })),
  getMemoryStatus: vi.fn(() => Promise.resolve({ active: '', builtin_files: { memory: 0, user: 0 } }))
}))

vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<typeof HermesApi>()),
  getCuratorStatus: mocks.getCuratorStatus,
  getMemoryStatus: mocks.getMemoryStatus
}))

beforeEach(() => {
  vi.clearAllMocks()
  resetServerCapabilities()
})

afterEach(cleanup)

describe('MaintenancePanel capability gating', () => {
  it('offers only the doctor on a Harvis admin and never asks for the curator', async () => {
    setServerCapabilities({ capabilities: { doctor: true, memory_reset: true } })
    render(<MaintenancePanel />)

    expect((await screen.findAllByRole('button', { name: /doctor/i })).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /security/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /backup/i })).toBeNull()
    expect(mocks.getCuratorStatus).not.toHaveBeenCalled()
  })

  it('hides the whole operations block when the person may run none of them', async () => {
    setServerCapabilities({ capabilities: { memory_reset: true } })
    render(<MaintenancePanel />)

    await screen.findByText(/memory/i)
    expect(screen.queryByRole('button', { name: /doctor/i })).toBeNull()
  })
})
