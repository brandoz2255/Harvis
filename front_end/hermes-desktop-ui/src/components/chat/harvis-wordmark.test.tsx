import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { HarvisWordmark } from './harvis-wordmark'

function installMatchMedia(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      addEventListener: vi.fn(),
      matches,
      media: '(prefers-reduced-motion: reduce)',
      onchange: null,
      removeEventListener: vi.fn()
    }))
  )
}

const wordmark = (container: HTMLElement) => container.querySelector('.harvis-cycle') as HTMLElement
const phases = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLElement>('.harvis-face')).map(el => el.dataset.phase)

describe('HarvisWordmark', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('starts on the original face, at rest, one letter per span', () => {
    installMatchMedia(false)
    const { container } = render(<HarvisWordmark />)

    expect(wordmark(container).dataset.transition).toBeUndefined()
    expect(phases(container)).toEqual(['rest'])
    expect(container.querySelectorAll('.harvis-letter')).toHaveLength('Harvis'.length)
    expect(wordmark(container).getAttribute('aria-label')).toBe('Harvis')
  })

  it('changes face with a different transition each time', () => {
    installMatchMedia(false)
    const { container } = render(<HarvisWordmark />)
    const seen: Array<string | undefined> = []

    for (let i = 0; i < 5; i += 1) {
      act(() => {
        vi.advanceTimersByTime(4200)
      })
      seen.push(wordmark(container).dataset.transition)
      expect(phases(container)).toEqual(['out', 'in'])
    }

    expect(seen).toEqual(['flip', 'glitch', 'rise', 'scramble', 'wipe'])
  })

  it('scramble ends on the real letters', () => {
    installMatchMedia(false)
    const { container } = render(<HarvisWordmark />)

    // Steps 1-3 are flip, glitch and rise; the fourth change scrambles.
    act(() => {
      vi.advanceTimersByTime(4200 * 4)
    })
    expect(wordmark(container).dataset.transition).toBe('scramble')

    act(() => {
      vi.advanceTimersByTime(1000)
    })
    const incoming = container.querySelector('.harvis-face[data-phase="in"]')
    expect(incoming?.textContent).toBe('Harvis')
  })

  it('holds still on the original face under reduced motion', () => {
    installMatchMedia(true)
    const { container } = render(<HarvisWordmark />)

    act(() => {
      vi.advanceTimersByTime(4200 * 3)
    })
    expect(phases(container)).toEqual(['rest'])
    expect(wordmark(container).dataset.transition).toBeUndefined()
  })
})
