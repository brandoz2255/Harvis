import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $followupsBySession, setFollowupStarter, setSessionFollowups } from '@/store/followups'

import { FollowupCards } from './followup-cards'

const CARDS = [
  { prompt: 'Add tests for the parser', title: 'Add parser tests' },
  { prompt: 'Update the changelog', title: 'Update changelog' }
]

describe('FollowupCards', () => {
  beforeEach(() => {
    $followupsBySession.set({})
    setFollowupStarter(null)
  })

  afterEach(() => {
    cleanup()
    $followupsBySession.set({})
    setFollowupStarter(null)
  })

  it('renders nothing without cards', () => {
    const { container } = render(<FollowupCards sessionId="s1" />)

    expect(container.childElementCount).toBe(0)
  })

  it('shows only the viewed session cards', () => {
    setSessionFollowups('s1', CARDS)
    setSessionFollowups('s2', [{ prompt: 'p', title: 'Other chat card' }])

    render(<FollowupCards sessionId="s1" />)

    expect(screen.getByText('Add parser tests')).toBeTruthy()
    expect(screen.getByText('Update changelog')).toBeTruthy()
    expect(screen.queryByText('Other chat card')).toBeNull()
  })

  it('Start sends that card prompt to a new chat and retires the cards', () => {
    const starter = vi.fn()
    setFollowupStarter(starter)
    setSessionFollowups('s1', CARDS)

    render(<FollowupCards sessionId="s1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start a new chat: Update changelog' }))

    expect(starter).toHaveBeenCalledWith('Update the changelog')
    expect(screen.queryByText('Update changelog')).toBeNull()
  })

  it('the x dismisses every card without starting anything', () => {
    const starter = vi.fn()
    setFollowupStarter(starter)
    setSessionFollowups('s1', CARDS)

    render(<FollowupCards sessionId="s1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss suggestions' }))

    expect(starter).not.toHaveBeenCalled()
    expect($followupsBySession.get()).toEqual({})
    expect(screen.queryByText('Add parser tests')).toBeNull()
  })
})
