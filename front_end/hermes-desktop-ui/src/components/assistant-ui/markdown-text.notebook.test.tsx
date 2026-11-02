import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { MarkdownTextContent } from './markdown-text'

afterEach(() => {
  cleanup()
  window.location.hash = ''
})

// A chat action ("make a notebook about Mars") answers with a notebook link; it has to come out of
// preprocessMarkdown -> Streamdown -> MarkdownLink as an in-app pill, not a new-tab anchor.
describe('MarkdownTextContent notebook pills', () => {
  it('renders a notebook link as a pill that opens the notebook in the app', async () => {
    render(
      <MarkdownTextContent
        isRunning={false}
        text={'I made the notebook **Mars**.\n\n[📓 Mars](#/notebooks?nb=3f2a-b9&make=quiz)'}
      />
    )

    const pill = await screen.findByTestId('notebook-pill')

    expect(pill.textContent).toBe('Mars')
    expect(pill.getAttribute('target')).toBeNull()
    fireEvent.click(pill)
    expect(window.location.hash).toBe('#/notebooks?nb=3f2a-b9&make=quiz')
  })

  it('leaves other hash links alone', async () => {
    render(<MarkdownTextContent isRunning={false} text="[elsewhere](#/notebooks?nb=x;alert)" />)

    expect(screen.queryByTestId('notebook-pill')).toBeNull()
  })
})
