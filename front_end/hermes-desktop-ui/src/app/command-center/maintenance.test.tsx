import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type * as HermesApi from '@/hermes'
import { $confirmRequest, settleConfirm } from '@/store/confirm'
import { resetServerCapabilities, setServerCapabilities } from '@/store/server-capabilities'

import { MaintenancePanel } from './maintenance'

const mocks = vi.hoisted(() => ({
  getCuratorStatus: vi.fn(() => Promise.resolve({ enabled: true, paused: false, last_run_at: null })),
  getMemoryStatus: vi.fn(() => Promise.resolve({ active: '', builtin_files: { memory: 0, user: 0 } })),
  shutdownServer: vi.fn(() => Promise.resolve({ ok: true }))
}))

vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<typeof HermesApi>()),
  getCuratorStatus: mocks.getCuratorStatus,
  getMemoryStatus: mocks.getMemoryStatus,
  shutdownServer: mocks.shutdownServer
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

describe('MaintenancePanel shut down button', () => {
  it('is not offered without the server watcher', async () => {
    setServerCapabilities({ capabilities: { doctor: true, memory_reset: true } })
    render(<MaintenancePanel />)

    await screen.findAllByRole('button', { name: /doctor/i })
    expect(screen.queryByRole('button', { name: /shut down/i })).toBeNull()
  })

  it('asks first, and only a yes shuts the server down', async () => {
    setServerCapabilities({ capabilities: { memory_reset: true, server_power: true } })
    render(<MaintenancePanel />)
    const button = await screen.findByRole('button', { name: /shut down harvis/i })

    fireEvent.click(button)
    await waitFor(() => expect($confirmRequest.get()?.destructive).toBe(true))
    settleConfirm(false)
    await waitFor(() => expect($confirmRequest.get()).toBeNull())
    expect(mocks.shutdownServer).not.toHaveBeenCalled()

    fireEvent.click(button)
    await waitFor(() => expect($confirmRequest.get()).not.toBeNull())
    settleConfirm(true)
    await waitFor(() => expect(mocks.shutdownServer).toHaveBeenCalledTimes(1))
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true))
  })
})
