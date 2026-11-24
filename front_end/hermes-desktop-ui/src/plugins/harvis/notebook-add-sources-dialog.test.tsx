import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NotebookDetail } from './notebook-detail'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

vi.mock('./notebook-share', () => ({ NotebookShareButton: () => null }))

const NB = 'nb-1'

const notebook = (role?: string) => ({
  id: NB,
  title: 'Untitled notebook',
  description: null,
  emoji: null,
  source_count: 0,
  note_count: 0,
  updated_at: '2026-11-03T00:00:00Z',
  ...(role ? { role } : {})
})

const ready = { id: 's1', type: 'url', title: 'Mars page', status: 'ready', error_message: null, chunk_count: 4 }

function mockRoutes(sources: unknown[], role?: string) {
  harvisApi.mockImplementation(
    routeApi({
      [`GET /api/notebooks/${NB}/sources`]: () => sources,
      [`GET /api/notebooks/${NB}/stats`]: () => ({ source_count: sources.length, chunk_count: 0, note_count: 0 }),
      [`GET /api/notebooks/${NB}/notes`]: () => ({ notes: [] }),
      [`GET /api/notebooks/${NB}/chat/history`]: () => ({ messages: [] }),
      [`GET /api/notebooks/${NB}`]: () => notebook(role),
      [`POST /api/notebooks/${NB}/sources/upload`]: () => ({ id: 'new' }),
      [`POST /api/notebooks/${NB}/discover/search`]: () => ({
        results: [{ site: 'nasa.gov', snippet: 'Rover', title: 'Perseverance', url: 'https://nasa.gov/p' }]
      })
    })
  )
}

const render = () => renderWithQuery(<NotebookDetail layout="columns" notebookId={NB} onDeleted={() => undefined} />)

beforeEach(() => {
  harvisApi.mockReset()
})
afterEach(cleanup)

describe('Add sources prompt', () => {
  it('opens by itself on an empty notebook with drop, web search and deep research', async () => {
    mockRoutes([])
    render()

    const dialog = await screen.findByRole('dialog', { name: 'Add sources' })
    expect(dialog.textContent).toMatch(/Drop files here/)
    expect(screen.getByRole('button', { name: /Search the web/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Deep research/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /a link/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /pasted text/ })).toBeTruthy()
  })

  it('uploads every dropped file and closes when they all went in', async () => {
    mockRoutes([])
    render()

    const zone = await screen.findByTestId('source-drop-zone')
    const files = [new File(['a'], 'notes.pdf'), new File(['b'], 'slides.pptx')]
    fireEvent.drop(zone, { dataTransfer: { files } })

    await waitFor(() =>
      expect(harvisApi.mock.calls.filter(c => c[0] === `/api/notebooks/${NB}/sources/upload`)).toHaveLength(2)
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('runs a web search from the prompt and offers the pages', async () => {
    mockRoutes([])
    render()

    fireEvent.click(await screen.findByRole('button', { name: /Search the web/ }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Search the web' }), { target: { value: 'mars rover' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('Perseverance')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Add as sources' })).toBeTruthy()
  })

  it('stays closed once a notebook has sources, but the header button opens it', async () => {
    mockRoutes([ready])
    render()

    await screen.findByText('Mars page')
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Add sources' }))
    expect(await screen.findByRole('dialog', { name: 'Add sources' })).toBeTruthy()
  })

  it('never asks a viewer, who cannot add sources', async () => {
    mockRoutes([], 'viewer')
    render()

    await screen.findByText(/No sources yet/)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Add sources' })).toBeNull()
  })
})
