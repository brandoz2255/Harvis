import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ArtifactView } from './notebook-artifact-view'
import { downloadFile, filenameFrom } from './notebook-artifact-data'
import type { Artifact } from './notebook-artifacts'

vi.mock('./api', () => ({ harvisApi: vi.fn() }))

const NB = 'nb-1'

const table = {
  audio_url: null,
  content: {
    columns: ['Rover', 'Landed'],
    rows: [{ cells: ['Perseverance', '2021'], source: 'Mars page' }, { cells: ['Curiosity', '2012'] }],
    title: 'Rovers'
  },
  created_at: '2026-10-30T00:00:00Z',
  error_message: null,
  format: 'json',
  id: 'a-table',
  kind: 'data_table',
  status: 'ready',
  title: 'Rovers'
} as unknown as Artifact

const deck = {
  ...table,
  content: {
    slides: [
      { bullets: ['Landed Feb 2021', 'Jezero crater'], notes: 'Say hello', source: 'Mars page', title: 'Perseverance' },
      { bullets: ['2012'], title: 'Curiosity' }
    ],
    title: 'Mars'
  },
  id: 'a-deck',
  kind: 'slides',
  title: 'Mars deck'
} as unknown as Artifact

let fetchSpy: ReturnType<typeof vi.spyOn>
let clicks: string[]

beforeEach(() => {
  clicks = []
  URL.createObjectURL = vi.fn(() => 'blob:x')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    clicks.push(`${this.download}`)
  })
  fetchSpy = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(
      new Response('data', { headers: { 'content-disposition': 'attachment; filename="rovers.csv"' }, status: 200 })
    )
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('data table artifact', () => {
  it('renders columns, rows and the model-noted source, then downloads the CSV', async () => {
    render(<ArtifactView artifact={table} notebookId={NB} onBack={() => undefined} />)

    expect(screen.getByRole('columnheader', { name: 'Rover' })).toBeTruthy()
    expect(screen.getByRole('columnheader', { name: 'Source' })).toBeTruthy()
    expect(screen.getByText('Perseverance')).toBeTruthy()
    expect(screen.getByText(/2 rows/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Download CSV/ }))
    await waitFor(() => expect(clicks).toEqual(['rovers.csv']))
    expect(fetchSpy).toHaveBeenCalledWith(
      `/onb-api/notebooks/${NB}/artifacts/a-table/export.csv`,
      expect.objectContaining({ credentials: 'include' })
    )
  })
})

describe('slides artifact', () => {
  it('shows the outline, switches slides, and downloads PowerPoint', async () => {
    render(<ArtifactView artifact={deck} notebookId={NB} onBack={() => undefined} />)

    expect(screen.getAllByText('Perseverance').length).toBeGreaterThan(0)
    expect(screen.getByText('Landed Feb 2021')).toBeTruthy()
    expect(screen.getByText('Say hello')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Curiosity/ }))
    expect(screen.queryByText('Landed Feb 2021')).toBeNull()
    expect(screen.getByText('2012')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Download PowerPoint/ }))
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        `/onb-api/notebooks/${NB}/artifacts/a-deck/export.pptx`,
        expect.objectContaining({ credentials: 'include' })
      )
    )
  })
})

describe('downloadFile', () => {
  it('surfaces the server reason when an export fails', async () => {
    fetchSpy.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'PowerPoint export needs the python-pptx package on the server.' }), {
        status: 501
      })
    )

    await expect(downloadFile('/x', 'a.pptx')).rejects.toThrow(/python-pptx/)
  })

  it('takes the file name from the header, preferring the UTF-8 form', () => {
    expect(filenameFrom('attachment; filename="a b.csv"', 'x.csv')).toBe('a b.csv')
    expect(filenameFrom('attachment; filename="a.csv"; filename*=UTF-8\'\'caf%C3%A9.csv', 'x.csv')).toBe('café.csv')
    expect(filenameFrom(null, 'x.csv')).toBe('x.csv')
  })
})
