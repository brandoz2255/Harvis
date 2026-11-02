import { cleanup, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Source } from './notebook-shared'
import { NotebookSourceViewer } from './notebook-source-viewer'
import { renderWithQuery } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const source: Source = {
  id: 's1',
  type: 'url',
  title: 'Mars page',
  status: 'ready',
  error_message: null,
  chunk_count: 4,
  original_filename: null
}

// Braces matter: a hook that returns the mock hands vitest a "cleanup function", which it then calls.
beforeEach(() => {
  harvisApi.mockReset()
})
afterEach(cleanup)

describe('NotebookSourceViewer', () => {
  it('shows the extracted text and its size', async () => {
    harvisApi.mockResolvedValue({
      source_id: 's1',
      title: 'Mars page',
      type: 'url',
      content: 'Jezero crater…',
      length: 14
    })

    renderWithQuery(<NotebookSourceViewer notebookId="nb-1" onClose={() => undefined} source={source} />)

    expect(await screen.findByText('Jezero crater…')).toBeTruthy()
    expect(screen.getByText('url, 4 passages, 14 characters')).toBeTruthy()
    expect(harvisApi).toHaveBeenCalledWith('/api/notebooks/nb-1/sources/s1/content')
  })

  it('says when nothing was extracted', async () => {
    harvisApi.mockResolvedValue({ source_id: 's1', title: null, type: 'pdf', content: '', length: 0 })
    renderWithQuery(<NotebookSourceViewer notebookId="nb-1" onClose={() => undefined} source={source} />)

    expect(await screen.findByText('Nothing was extracted from this source.')).toBeTruthy()
  })

  it('shows the backend error instead of spinning forever', async () => {
    harvisApi.mockImplementation(async () => {
      throw new Error('Source not found')
    })
    renderWithQuery(<NotebookSourceViewer notebookId="nb-1" onClose={() => undefined} source={source} />)

    expect(await screen.findByText('Source not found')).toBeTruthy()
  })

  it('renders nothing while no source is picked', () => {
    renderWithQuery(<NotebookSourceViewer notebookId="nb-1" onClose={() => undefined} source={null} />)

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(harvisApi).not.toHaveBeenCalled()
  })

  describe('with a cited passage', () => {
    const content = 'Page one text.\nPage two begins here. Jezero crater held a lake.\nMore.'

    const load = (extra: Record<string, unknown> = {}) =>
      harvisApi.mockResolvedValue({
        source_id: 's1',
        title: 'Mars page',
        type: 'pdf',
        content,
        length: content.length,
        ...extra
      })

    it('marks the range from the stored offsets and scrolls it into view', async () => {
      load()
      const scroll = vi.fn()
      Element.prototype.scrollIntoView = scroll
      const start = content.indexOf('Jezero')

      renderWithQuery(
        <NotebookSourceViewer
          notebookId="nb-1"
          onClose={() => undefined}
          source={source}
          target={{ end_char: start + 26, page: 2, snippet: 'Jezero crater held a lake.', start_char: start }}
        />
      )

      const mark = await screen.findByTestId('cited-passage')
      expect(mark.textContent).toBe('Jezero crater held a lake.')
      expect(screen.getByText('Cited passage marked (page 2).')).toBeTruthy()
      expect(scroll).toHaveBeenCalled()
    })

    it('finds the passage by its snippet when the citation has no offsets', async () => {
      load()

      renderWithQuery(
        <NotebookSourceViewer
          notebookId="nb-1"
          onClose={() => undefined}
          source={source}
          target={{ quote: 'Page two begins here.' }}
        />
      )

      expect((await screen.findByTestId('cited-passage')).textContent).toBe('Page two begins here')
    })

    it('jumps to the page start when only the page is known', async () => {
      load({ page_starts: [0, 15] })

      renderWithQuery(
        <NotebookSourceViewer notebookId="nb-1" onClose={() => undefined} source={source} target={{ page: 2 }} />
      )

      expect(await screen.findByTestId('cited-page')).toBeTruthy()
      expect(screen.queryByTestId('cited-passage')).toBeNull()
      expect(screen.getByText('Jumped to page 2; the exact passage could not be marked.')).toBeTruthy()
    })

    it('says so when the passage cannot be found', async () => {
      load()

      renderWithQuery(
        <NotebookSourceViewer
          notebookId="nb-1"
          onClose={() => undefined}
          source={source}
          target={{ snippet: 'Something that was never in this source' }}
        />
      )

      expect(await screen.findByText('The cited passage could not be found in the text.')).toBeTruthy()
      expect(screen.queryByTestId('cited-passage')).toBeNull()
    })
  })
})
