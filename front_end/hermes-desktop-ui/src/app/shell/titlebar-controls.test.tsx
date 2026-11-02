import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n'
import { $islandExplore, $islandVisible } from '@/mods/store'
import { $harvisMicOn, $voiceCallLive } from '@/store/voice-call'

import { TitlebarControls } from './titlebar-controls'

function renderControls() {
  return render(
    <I18nProvider configClient={null} initialLocale="en">
      <MemoryRouter initialEntries={['/']}>
        <TitlebarControls onOpenSettings={vi.fn()} />
      </MemoryRouter>
    </I18nProvider>
  )
}

afterEach(() => {
  cleanup()
  $voiceCallLive.set(false)
  $harvisMicOn.set(false)
  $islandExplore.set(false)
  $islandVisible.set(false)
})

// The Harvis button is the assistant that moves around the app; the composer's
// mic stays the plain talk-to-this-chat call.
describe('Harvis titlebar button', () => {
  it('is an on/off toggle for the bottom mic: on shows it without starting a call, off hides it', () => {
    expect($harvisMicOn.get()).toBe(false)
    renderControls()

    fireEvent.click(screen.getByLabelText('Turn Harvis on — shows the Harvis mic at the bottom'))
    expect($harvisMicOn.get()).toBe(true)
    expect($voiceCallLive.get()).toBe(false)

    // Off also ends a call that was running.
    $voiceCallLive.set(true)
    fireEvent.click(screen.getByLabelText('Turn Harvis off — hides the Harvis mic'))
    expect($voiceCallLive.get()).toBe(false)
    expect($harvisMicOn.get()).toBe(false)
  })

  it('sits right before the layout editor', () => {
    renderControls()

    const labels = Array.from(document.querySelectorAll('button[aria-label]')).map(b => b.getAttribute('aria-label'))
    const harvis = labels.indexOf('Turn Harvis on — shows the Harvis mic at the bottom')

    expect(harvis).toBeGreaterThanOrEqual(0)
    expect(labels[harvis + 1]).toBe('Layout editor')
  })
})

// The map opens the bot island full screen from any chat, not only the idle Bots tab.
describe('Island map titlebar button', () => {
  it('opens and closes the full-screen map', () => {
    $islandVisible.set(true)
    renderControls()

    fireEvent.click(screen.getByLabelText('Open the bot island map'))
    expect($islandExplore.get()).toBe(true)

    fireEvent.click(screen.getByLabelText('Close the bot island map'))
    expect($islandExplore.get()).toBe(false)
  })

  it('is hidden when the island is turned off', () => {
    renderControls()

    expect(screen.queryByLabelText('Open the bot island map')).toBeNull()
  })

  it('keeps Harvis right before the layout editor', () => {
    $islandVisible.set(true)
    renderControls()

    const labels = Array.from(document.querySelectorAll('button[aria-label]')).map(b => b.getAttribute('aria-label'))
    const harvis = labels.indexOf('Turn Harvis on — shows the Harvis mic at the bottom')

    expect(labels[harvis - 1]).toBe('Open the bot island map')
    expect(labels[harvis + 1]).toBe('Layout editor')
  })
})
