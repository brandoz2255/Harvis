import { render } from '@testing-library/react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $petActivity, flashPetActivity, setPetActivity } from '@/store/pet'
import { $busy, setGatewayState } from '@/store/session'

import { HarvisFace, harvisFaceMood } from './harvis-face'

const face = (root: HTMLElement) => root.querySelector('.hv-face') as HTMLElement

describe('harvisFaceMood', () => {
  it('maps the chat activity states the desktop pet uses', () => {
    expect(harvisFaceMood('idle', 'open')).toBe('idle')
    expect(harvisFaceMood('review', 'open')).toBe('thinking')
    expect(harvisFaceMood('run', 'open')).toBe('working')
    expect(harvisFaceMood('waiting', 'open')).toBe('waiting')
    expect(harvisFaceMood('wave', 'open')).toBe('success')
    expect(harvisFaceMood('jump', 'open')).toBe('success')
    expect(harvisFaceMood('failed', 'open')).toBe('error')
  })

  it('sleeps when the gateway is gone, but not before the first connect', () => {
    expect(harvisFaceMood('run', 'closed')).toBe('sleeping')
    expect(harvisFaceMood('idle', 'error')).toBe('sleeping')
    expect(harvisFaceMood('idle', 'idle')).toBe('idle')
    expect(harvisFaceMood('idle', 'connecting')).toBe('idle')
  })
})

describe('HarvisFace', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    $petActivity.set({})
    $busy.set(false)
    setGatewayState('open')
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('follows the live chat activity', () => {
    const { container } = render(<HarvisFace live />)
    expect(face(container).dataset.mood).toBe('idle')

    act(() => {
      $busy.set(true)
      setPetActivity({ reasoning: true })
    })
    expect(face(container).dataset.mood).toBe('thinking')

    act(() => setPetActivity({ reasoning: false, toolRunning: true }))
    expect(face(container).dataset.mood).toBe('working')

    act(() => {
      $busy.set(false)
      flashPetActivity({ error: true })
    })
    expect(face(container).dataset.mood).toBe('error')

    act(() => vi.advanceTimersByTime(1700))
    expect(face(container).dataset.mood).toBe('idle')
  })

  it('a fixed mood ignores the chat', () => {
    const { container } = render(<HarvisFace mood="waiting" />)
    act(() => setPetActivity({ busy: true, toolRunning: true }))
    expect(face(container).dataset.mood).toBe('waiting')
  })

  it('looks around and waves while idle, like the old mascot', () => {
    const { container } = render(<HarvisFace />)
    const poses = [face(container).dataset.pose]

    for (let i = 0; i < 6; i++) {
      act(() => vi.advanceTimersByTime(2000))
      poses.push(face(container).dataset.pose)
    }

    expect(poses).toEqual(['center', 'left', 'center', 'right', 'center', 'wave', 'center'])
  })

  it('a click startles it; four quick clicks make it cross, then it calms down', () => {
    const { container } = render(<HarvisFace interactive />)
    const button = face(container)
    expect(button.tagName).toBe('BUTTON')

    act(() => button.click())
    expect(button.dataset.poke).toBe('startled')
    act(() => vi.advanceTimersByTime(350))
    expect(button.dataset.poke).toBeUndefined()

    act(() => {
      button.click()
      button.click()
      button.click()
    })
    expect(button.dataset.poke).toBe('angry')
    act(() => button.click())
    expect(button.dataset.poke).toBe('angry')
    act(() => vi.advanceTimersByTime(1100))
    expect(button.dataset.poke).toBeUndefined()
  })

  it('is not a button unless it is interactive', () => {
    const { container } = render(<HarvisFace label="Harvis" />)
    expect(face(container).tagName).toBe('SPAN')
    expect(face(container).getAttribute('role')).toBe('img')
  })
})
