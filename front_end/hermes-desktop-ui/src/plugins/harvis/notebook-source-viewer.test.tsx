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
})
