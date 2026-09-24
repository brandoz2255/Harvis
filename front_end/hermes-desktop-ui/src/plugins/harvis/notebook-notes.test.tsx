import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NotebookNotes } from './notebook-notes'
import { routeApi } from './notebook-test-utils'
import { renderWithQuery } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const NB = 'nb-1'

const notes = [
  {
    id: 'n1',
    type: 'user_note',
    title: 'Reading plan',
    content: 'Chapter 3 first',
    is_pinned: false,
    source_meta: {},
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z'
  },
  {
    id: 'n2',
    type: 'ai_note',
    title: null,
    content: 'The rover landed in 2021.',
    is_pinned: true,
    source_meta: {},
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z'
  }
]

beforeEach(() => {
  harvisApi.mockReset()
  harvisApi.mockImplementation(
    routeApi({
      [`GET /api/notebooks/${NB}/notes`]: () => ({ notes, total_count: 2, has_more: false }),
      [`POST /api/notebooks/${NB}/notes`]: () => ({ ...notes[0], id: 'n3' }),
      [`PATCH /api/notebooks/${NB}/notes/`]: () => notes[0],
      [`DELETE /api/notebooks/${NB}/notes/`]: () => ({ message: 'ok' })
    })
  )
})

afterEach(cleanup)

describe('NotebookNotes', () => {
  it('lists notes with the pinned one first and an AI badge on saved answers', async () => {
    renderWithQuery(<NotebookNotes notebookId={NB} />)

    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0].textContent).toContain('The rover landed in 2021.')
    expect(items[0].textContent).toContain('AI')
    expect(items[1].textContent).toContain('Reading plan')
  })

  it('creates a user note with the typed title and content', async () => {
    renderWithQuery(<NotebookNotes notebookId={NB} />)
    await screen.findAllByRole('listitem')

    fireEvent.click(screen.getByRole('button', { name: /new note/i }))
    fireEvent.change(screen.getByPlaceholderText('Title (optional)'), { target: { value: 'Todo' } })
    fireEvent.change(screen.getByPlaceholderText('Write a note…'), { target: { value: 'Re-read the abstract' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save note' }))

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `/api/notebooks/${NB}/notes`,
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ content: 'Re-read the abstract', title: 'Todo', type: 'user_note' })
        })
      )
    )
  })

  it('pins and unpins through PATCH is_pinned', async () => {
    renderWithQuery(<NotebookNotes notebookId={NB} />)
    await screen.findAllByRole('listitem')

    fireEvent.click(screen.getByRole('button', { name: 'Unpin note' }))

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `/api/notebooks/${NB}/notes/n2`,
        expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ is_pinned: false }) })
      )
    )
  })

  it('shows the backend error instead of spinning forever', async () => {
    harvisApi.mockImplementation(async () => {
      throw new Error('Notebook not found')
    })

    renderWithQuery(<NotebookNotes notebookId={NB} />)

    expect(await screen.findByText('Notebook not found')).toBeTruthy()
  })
})
