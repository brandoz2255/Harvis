/**
 * A deep-research reply in chat ends with a link to `#/research?id=rp-…`.
 * Following it has to open that run's report, not the "new research" form.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

const calls: string[] = []

vi.mock('./api', () => ({
  harvisApi: vi.fn(async (path: string) => {
    calls.push(path)

    if (path.startsWith('/api/research/detail/')) {
      return { query: 'perovskite stability', result: '# Findings', sources: [], stats: {} }
    }

    if (path.startsWith('/api/research/active')) {
      return { active: [] }
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
