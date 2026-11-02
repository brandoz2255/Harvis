import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AboutSettings } from './about-settings'

vi.mock('@/store/updates', async () => {
  const { atom } = await import('nanostores')

  return {
    $desktopVersion: atom(null),
    $updateApply: atom({
      applying: false,
      stage: 'idle',
      message: '',
      percent: null,
      error: null,
      command: null,
      log: []
    }),
    $updateChecking: atom(false),
    $updateStatus: atom(null),
    checkUpdates: vi.fn(),
    openUpdatesWindow: vi.fn(),
    refreshDesktopVersion: vi.fn(async () => {}),
    startActiveUpdate: vi.fn()
  }
})

vi.mock('./uninstall-section', () => ({ UninstallSection: () => null }))

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('AboutSettings legal row', () => {
  it('opens the terms from Settings, including on a server without them', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 404 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<AboutSettings />)

    expect(screen.getByText('Terms and Acceptable Use')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Read' }))

    expect(await screen.findByRole('dialog', { name: 'Terms and Acceptable Use' })).toBeTruthy()
    expect(await screen.findByText(/does not publish its terms yet/)).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith('/api/legal', expect.anything())
  })
})

describe('AboutSettings automatic updates row', () => {
  afterEach(() => {
    delete (window as { hermesDesktop?: unknown }).hermesDesktop
  })

  it('shows the row in the Electron shell', () => {
    ;(window as { hermesDesktop?: unknown }).hermesDesktop = { webShell: false }
    render(<AboutSettings />)

    expect(screen.getByText('Automatic updates')).toBeTruthy()
  })

  it('hides the row in the served web build, where the bridge is a stub', () => {
    ;(window as { hermesDesktop?: unknown }).hermesDesktop = { webShell: true }
    render(<AboutSettings />)

    expect(screen.queryByText('Automatic updates')).toBeNull()
  })
})
