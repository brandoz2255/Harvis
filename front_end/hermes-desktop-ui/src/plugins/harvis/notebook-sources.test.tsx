import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getContextLevels, setContextLevel } from './notebook-selection'
import type { Source } from './notebook-shared'
import { NotebookSources } from './notebook-sources'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const NB = 'nb-1'

const source = (over: Record<string, unknown>) =>
  ({
    chunk_count: 3,
    error_message: null,
    id: 's1',
    original_filename: null,
    status: 'ready',
    title: 'Mars page',
    type: 'url',
    ...over
  }) as unknown as Source

let embedder: Record<string, unknown> | null = null

beforeEach(() => {
  window.localStorage.clear()
  harvisApi.mockReset()
  embedder = null
  harvisApi.mockImplementation(
    routeApi({
      'GET /api/capabilities/notebooks-embedder': () => {
        if (!embedder) {
          throw new Error('unreachable')
        }

        return embedder
      },
      'GET /api/notebooks/meta/capabilities': () => ({
        audio_sources: { ready: true, reason: '' },
        deep_research: { ready: true, reason: '' },
        embedder: { ready: true, reason: '' },
        image_sources: { ready: true, reason: '' },
        podcast_audio: { ready: true, reason: '' },
        web_search: { ready: true, reason: '' }
      }),
      [`POST /api/notebooks/${NB}/sources/s1/reindex`]: () => ({ message: 'Re-indexing started', queued: 1 }),
      [`POST /api/notebooks/${NB}/reindex`]: () => ({
        message: 'Re-indexing started',
        queued: 1,
        skipped: [{ reason: 'the original file is gone', source_id: 's2', title: 'Old PDF' }]
      }),
      [`POST /api/notebooks/${NB}/sources/s3/retry`]: () => ({ ok: true }),
      'POST /api/capabilities/notebooks-embedder/install': () => ({ ok: true })
    })
  )
})

afterEach(cleanup)

const clicked = (path: string) => harvisApi.mock.calls.some(c => c[0] === path && c[1]?.method === 'POST')

describe('NotebookSources', () => {
  it('lets the file picker take pptx, xlsx, epub and PDFs and says scans are read', async () => {
    const { container } = renderWithQuery(<NotebookSources notebookId={NB} sources={[]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Upload a file' }))

    const accept = container.querySelector('input[type="file"]')?.getAttribute('accept') ?? ''
    expect(accept.split(',')).toEqual(expect.arrayContaining(['.pdf', '.pptx', '.xlsx', '.epub']))
    expect(screen.getByText(/scans are read with OCR/)).toBeTruthy()
  })

  it('shows summary progress and ingest notices on the source row', () => {
    renderWithQuery(
      <NotebookSources
        notebookId={NB}
        sources={[
          source({ metadata: { insights_status: 'pending' } }),
          source({
            id: 's2',
            metadata: { ingest_notice: '2 scanned pages were not read.', insights_status: 'error' },
            title: 'Scan'
          })
        ]}
      />
    )

    expect(screen.getByText(/writing a summary/)).toBeTruthy()
    expect(screen.getByText(/no summary/)).toBeTruthy()
    expect(screen.getByText('2 scanned pages were not read.')).toBeTruthy()
  })

  it('stores a per-source context level and counts what chat reads', () => {
    renderWithQuery(<NotebookSources notebookId={NB} sources={[source({}), source({ id: 's2', title: 'Other' })]} />)
    expect(screen.getByText('Chat reads 2 of 2 sources')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'More for Mars page' }))
    const group = screen.getByRole('group', { name: 'What chat reads of Mars page' })
    fireEvent.click(group.querySelector('button[title^="Chat ignores"]') as HTMLElement)

    expect(getContextLevels(NB)).toEqual({ s1: 'off' })
    expect(screen.getByText('Chat reads 1 of 2 sources')).toBeTruthy()
  })

  it('ticks sources in and out like Gemini Notebook, with Select all', () => {
    setContextLevel(NB, 's1', 'full')
    setContextLevel(NB, 's2', 'full')
    renderWithQuery(<NotebookSources notebookId={NB} sources={[source({}), source({ id: 's2', title: 'Other' })]} />)
    const mars = screen.getByRole('checkbox', { name: 'Use Mars page' })
    expect(mars.getAttribute('aria-checked')).toBe('true')

    fireEvent.click(mars)
    expect(getContextLevels(NB)).toEqual({ s1: 'off' })
    expect(screen.getByRole('checkbox', { name: 'Select all sources' }).getAttribute('aria-checked')).toBe('mixed')

    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all sources' }))
    expect(getContextLevels(NB).s1 ?? 'full').toBe('full')
    expect(screen.getByText('Chat reads 2 of 2 sources')).toBeTruthy()

    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all sources' }))
    expect(screen.getByText('Chat reads 0 of 2 sources')).toBeTruthy()
  })

  it('re-indexes one source and the whole notebook, reporting what was skipped', async () => {
    renderWithQuery(<NotebookSources notebookId={NB} sources={[source({})]} />)

    fireEvent.click(screen.getByRole('button', { name: 'More for Mars page' }))
    fireEvent.click(screen.getByRole('button', { name: 'Re-index Mars page' }))
    await waitFor(() => expect(clicked(`/api/notebooks/${NB}/sources/s1/reindex`)).toBe(true))

    fireEvent.click(screen.getByRole('button', { name: /Re-index all/ }))
    expect(await screen.findByText(/Skipped 1: Old PDF \(the original file is gone\)/)).toBeTruthy()
  })

  it('offers the embedding model inline and retries failed sources once it is installed', async () => {
    embedder = {
      download_mb: 274,
      install_tag: 'nomic-embed-text',
      model: null,
      reason: 'needs the model',
      state: 'not_installed'
    }
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('data: {"status":"success"}\n\n', { status: 200 }))

    renderWithQuery(
      <NotebookSources
        notebookId={NB}
        sources={[source({ error_message: 'no embedder', id: 's3', status: 'error' })]}
      />
    )

    fireEvent.click(await screen.findByRole('button', { name: /Install \(274 MB\)/ }))

    await waitFor(() => expect(clicked(`/api/notebooks/${NB}/sources/s3/retry`)).toBe(true))
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/capabilities/notebooks-embedder/install',
      expect.objectContaining({ method: 'POST' })
    )
    fetchSpy.mockRestore()
  })

  it('tells the person when cloud embeddings are on', async () => {
    embedder = {
      download_mb: null,
      install_tag: null,
      leaves_machine: true,
      model: 'text-embedding-3-small',
      provider: 'openai',
      reason: 'sent there',
      state: 'ready'
    }
    renderWithQuery(<NotebookSources notebookId={NB} sources={[]} />)

    expect(await screen.findByText(/Cloud embeddings are on/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Install/ })).toBeNull()
  })
})
