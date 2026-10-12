import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NotebookDiscover } from './notebook-discover'
import { NotebookSources } from './notebook-sources'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const NB = 'nb-1'
const D = `/api/notebooks/${NB}/discover`

const ok = { reason: '', ready: true }

const caps = (over: Record<string, unknown> = {}) => ({
  audio_sources: ok,
  deep_research: ok,
  embedder: ok,
  image_sources: ok,
  podcast_audio: ok,
  web_search: ok,
  ...over
})

let capabilities = caps()
let statusBody: Record<string, unknown> = {}

const found = [
  { site: 'nasa.gov', snippet: 'Mars facts', title: 'Mars overview', url: 'https://nasa.gov/mars' },
  { site: 'esa.int', snippet: 'Rovers', title: 'Rover missions', url: 'https://esa.int/rovers' }
]

beforeEach(() => {
  harvisApi.mockReset()
  capabilities = caps()
  statusBody = { message: 'Reading page 3', phase: 'extracting', query: 'mars', session_id: 'rp-1', status: 'running' }
  harvisApi.mockImplementation(
    routeApi({
      'GET /api/notebooks/meta/capabilities': () => capabilities,
      'GET /api/workspace/providers': () => ({ providers: [] }),
      [`POST ${D}/search`]: () => ({ query: 'mars', results: found }),
      [`POST ${D}/add`]: (_p, init) => ({
        added: (JSON.parse(String(init?.body)).items as { title: string; url: string }[]).map((i, n) => ({
          id: `s${n}`,
          ...i
        })),
        skipped: []
      }),
      [`POST ${D}/deep/rp-1/cancel`]: () => ({ cancelled: true }),
      [`POST ${D}/deep/rp-1/import`]: () => ({
        already_added: false,
        cited: [{ site: 'nasa.gov', snippet: '', title: 'Mars overview', url: 'https://nasa.gov/mars' }],
        source: { id: 'r1', title: 'Research: mars' }
      }),
      [`POST ${D}/deep`]: () => ({ session_id: 'rp-1', status: 'running' }),
      [`GET ${D}/deep/rp-1`]: () => statusBody
    })
  )
})

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

describe('Fast research', () => {
  it('searches, lists title and site, and adds only the ticked pages as sources', async () => {
    const onAdded = vi.fn()
    renderWithQuery(<NotebookDiscover notebookId={NB} onAdded={onAdded} />)

    fireEvent.change(screen.getByLabelText('Search the web'), { target: { value: 'mars rovers' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('Mars overview')).toBeTruthy()
    expect(screen.getByText('nasa.gov')).toBeTruthy()
    expect(screen.getByText('Rovers')).toBeTruthy()

    const add = screen.getByRole('button', { name: /Add as sources/ }) as HTMLButtonElement
    expect(add.disabled).toBe(true)

    fireEvent.click(screen.getByLabelText('Select Rover missions'))
    fireEvent.click(screen.getByRole('button', { name: 'Add as sources (1)' }))

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `${D}/add`,
        expect.objectContaining({
          body: JSON.stringify({ items: [{ title: 'Rover missions', url: 'https://esa.int/rovers' }] }),
          method: 'POST'
        })
      )
    )
    expect(await screen.findByText(/Added 1 source; they are being read now\./)).toBeTruthy()
    expect(onAdded).toHaveBeenCalled()
  })

  it('says so when nothing is found, and shows a server error in words', async () => {
    harvisApi.mockImplementation(
      routeApi({
        'GET /api/notebooks/meta/capabilities': () => capabilities,
        [`POST ${D}/search`]: () => {
          throw new Error('The web search did not answer. Try again in a moment.')
        }
      })
    )
    renderWithQuery(<NotebookDiscover notebookId={NB} onAdded={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search the web'), { target: { value: 'zzz' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText('The web search did not answer. Try again in a moment.')).toBeTruthy()
  })

  it('is disabled with the reason when the server has no web search', async () => {
    capabilities = caps({ web_search: { ready: false, reason: 'Web search is not available on this server.' } })
    renderWithQuery(<NotebookDiscover notebookId={NB} onAdded={vi.fn()} />)

    expect(await screen.findByText('Web search is not available on this server.')).toBeTruthy()
    expect((screen.getByLabelText('Search the web') as HTMLInputElement).disabled).toBe(true)
  })
})

describe('Deep research', () => {
  const startDeep = () => {
    fireEvent.click(screen.getByRole('button', { name: /Deep research/ }))
    fireEvent.change(screen.getByLabelText('Research question'), { target: { value: 'mars water history' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  }

  it('shows progress while running and can be cancelled', async () => {
    renderWithQuery(<NotebookDiscover notebookId={NB} onAdded={vi.fn()} />)
    startDeep()

    expect(await screen.findByText('Reading page 3')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(`${D}/deep/rp-1/cancel`, expect.objectContaining({ method: 'POST' }))
    )
  })

  it('adds the report as a source and offers the cited pages for import', async () => {
    statusBody = { ...statusBody, status: 'done' }
    const onAdded = vi.fn()
    renderWithQuery(<NotebookDiscover notebookId={NB} onAdded={onAdded} />)
    startDeep()

    fireEvent.click(await screen.findByRole('button', { name: 'Add report as a source' }))
    expect(await screen.findByText(/Added the report: Research: mars\./)).toBeTruthy()
    expect(screen.getByText('Pages it cited')).toBeTruthy()

    fireEvent.click(screen.getByLabelText('Select Mars overview'))
    fireEvent.click(screen.getByRole('button', { name: 'Add cited pages (1)' }))
    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `${D}/add`,
        expect.objectContaining({
          body: JSON.stringify({ items: [{ title: 'Mars overview', url: 'https://nasa.gov/mars' }] })
        })
      )
    )
  })

  it('shows a failed run in words and lets the person try again', async () => {
    statusBody = { ...statusBody, error: 'Ollama has no usable model.', status: 'error' }
    renderWithQuery(<NotebookDiscover notebookId={NB} onAdded={vi.fn()} />)
    startDeep()
    expect(await screen.findByText('Ollama has no usable model.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })
})

describe('Sources panel gating', () => {
  it('refuses an audio file with the reason instead of failing silently', async () => {
    capabilities = caps({
      audio_sources: {
        ready: false,
        reason: 'This server has no speech-to-text turned on, so audio files cannot be transcribed.'
      }
    })
    const { container } = renderWithQuery(<NotebookSources notebookId={NB} sources={[]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Upload a file' }))
    expect(await screen.findByText(/Audio: This server has no speech-to-text/)).toBeTruthy()

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [new File(['x'], 'talk.mp3', { type: 'audio/mpeg' })] } })

    expect(await screen.findAllByText(/no speech-to-text turned on/)).toHaveLength(2)
    expect(harvisApi.mock.calls.some(c => c[0].includes('/sources/upload'))).toBe(false)
  })

  it('has a Discover tab', async () => {
    renderWithQuery(<NotebookSources notebookId={NB} sources={[]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Discover' }))
    expect(await screen.findByLabelText('Search the web')).toBeTruthy()
  })
})
