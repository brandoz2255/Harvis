import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n'

import { HarvisVoiceOrb } from './harvis-voice-orb'
import type { ConversationStatus } from './hooks/use-voice-conversation'

function renderOrb(status: ConversationStatus, muted = false) {
  const onEnd = vi.fn()
  const onToggleMute = vi.fn()

  render(
    <I18nProvider configClient={null} initialLocale="en">
      <HarvisVoiceOrb level={0.5} muted={muted} onEnd={onEnd} onToggleMute={onToggleMute} status={status} />
    </I18nProvider>
  )

  return { onEnd, onToggleMute }
}

describe('HarvisVoiceOrb', () => {
  it.each([
    ['listening', 'Listening'],
    ['transcribing', 'Transcribing'],
    ['thinking', 'Thinking'],
    ['speaking', 'Speaking']
  ] as const)('says %s', (status, label) => {
    renderOrb(status)
    expect(screen.getByRole('status').textContent).toBe(label)
    expect(document.querySelector('[data-slot="harvis-voice-orb"]')?.getAttribute('data-status')).toBe(status)
  })

  it('shows muted while listening with the mic off', () => {
    renderOrb('listening', true)
    expect(screen.getByRole('status').textContent).toBe('Muted')
    expect(screen.getByLabelText('Unmute microphone').getAttribute('aria-pressed')).toBe('true')
  })

  it('ends the conversation and toggles the mic', () => {
    const { onEnd, onToggleMute } = renderOrb('listening')
    fireEvent.click(screen.getByLabelText('Mute microphone'))
    fireEvent.click(screen.getByLabelText('End voice conversation'))
    expect(onToggleMute).toHaveBeenCalledOnce()
    expect(onEnd).toHaveBeenCalledOnce()
  })
})
