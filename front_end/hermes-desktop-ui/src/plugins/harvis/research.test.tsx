/**
 * A deep-research reply in chat ends with a link to `#/research?id=rp-…`.
 * Following it has to open that run's report, not the "new research" form.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

const calls: string[] = []
let active: object[] = []

vi.mock('./api', () => ({
  harvisApi: vi.fn(async (path: string) => {
    calls.push(path)

    if (path.startsWith('/api/research/detail/')) {
      return { query: 'perovskite stability', result: '# Findings', sources: [], stats: {} }
    }

    if (path.startsWith('/api/research/active')) {
      return { active }
    }

    return { research: [] }
  })
}))

const { ResearchPage } = await import('./research')

function renderAt(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <ResearchPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('the research page opens the run a chat link names', () => {
  it('shows the linked report', async () => {
    renderAt('/research?id=rp-0123456789ab')

    expect(await screen.findByText('perovskite stability')).toBeTruthy()
    expect(calls).toContain('/api/research/detail/rp-0123456789ab')
  })

  it('starts on the new-research form without a link', async () => {
    calls.length = 0
    renderAt('/research')

    await screen.findByText('No research yet.')
    expect(calls.some(p => p.startsWith('/api/research/detail/'))).toBe(false)
  })
})

describe('a running research job shows its time against the plan', () => {
  const run = (elapsed: number) => ({
    elapsed,
    progress: { phase: 'writing', total_sources: 12 },
    query: 'heat pumps in cold climates',
    session_id: 'rp-aaaaaaaaaaaa',
    started_at: 0,
    time_budget: 120
  })

  it('names the planned time while inside it', async () => {
    active = [run(70)]
    renderAt('/research?id=rp-aaaaaaaaaaaa')

    expect(await screen.findByText(/Running for 1 min of a planned 2 min\./)).toBeTruthy()
    expect(screen.getByText(/Writing the report, 12 pages read · 1 min/)).toBeTruthy()
  })

  it('says it keeps going once the plan is passed', async () => {
    active = [run(361)]
    renderAt('/research?id=rp-aaaaaaaaaaaa')

    expect(
      await screen.findByText(/Running for 6 min, past the planned 2 min\. Harvis keeps going until the report is written\./)
    ).toBeTruthy()
    active = []
  })
})
