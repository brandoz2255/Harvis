import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { Panel, PanelRowMenu } from './panel'

beforeAll(() => {
  Element.prototype.hasPointerCapture ??= () => false
  Element.prototype.releasePointerCapture ??= () => undefined
  Element.prototype.setPointerCapture ??= () => undefined
  HTMLElement.prototype.scrollIntoView ??= () => undefined
})

describe('PanelRowMenu', () => {
  afterEach(() => {
    cleanup()
  })

  it('opens its actions menu from the kebab without a tooltip', async () => {
    const onSelect = vi.fn()

    render(<PanelRowMenu items={[{ label: 'Rename', onSelect }]} />)

    const trigger = screen.getByRole('button', { name: 'Actions' })

    expect(trigger.closest('[data-slot="tooltip-trigger"]')).toBeNull()

    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: 'mouse' })
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Rename' }))

    expect(onSelect).toHaveBeenCalledOnce()
  })
})

describe('Panel', () => {
  afterEach(() => {
    cleanup()
  })

  it('pops up over a dimmed backdrop that closes it when clicked', () => {
    const onClose = vi.fn()
    const { container } = render(<Panel onClose={onClose}>jobs</Panel>)
    const backdrop = container.querySelector('[data-overlay-surface]') as HTMLElement

    expect(backdrop.className).toContain('bg-black/22')
    fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('sits like a page when quiet: no dimming, and a click beside it does not close it', () => {
    const onClose = vi.fn()
    const { container } = render(
      <Panel onClose={onClose} quiet>
        jobs
      </Panel>
    )
    const backdrop = container.querySelector('[data-overlay-surface]') as HTMLElement

    expect(backdrop.className).not.toContain('bg-black')
    expect(backdrop.className).not.toContain('backdrop-blur')
    fireEvent.click(backdrop)
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
