import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { DirectiveContent } from '@/components/assistant-ui/directive-text'
import { GeneratedImage } from '@/components/chat/generated-image-result'

afterEach(cleanup)

// The legal text promises a remote image in chat waits for a click. These two
// paths render outside markdown, so they need their own gate.
describe('remote images outside markdown', () => {
  it('holds a generated image from another host until clicked', () => {
    const { container } = render(<GeneratedImage result={{ image: 'https://collector.example/g.png?d=secret' }} />)

    expect(container.querySelector('img[src*="collector.example"]')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /load image from collector\.example/i }))
    expect(container.querySelector('img[src*="collector.example"]')).not.toBeNull()
  })

  it('holds an @image link from another host until clicked', () => {
    const { container } = render(<DirectiveContent text="@image:https://collector.example/u.png" />)

    expect(container.querySelector('img[src*="collector.example"]')).toBeNull()
    expect(screen.getByRole('button', { name: /load image from collector\.example/i })).toBeTruthy()
  })
})
