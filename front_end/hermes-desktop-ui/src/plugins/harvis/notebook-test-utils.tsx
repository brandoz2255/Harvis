/** Test-only helpers for the notebook components: a fresh query client per render and a path-routed API mock. */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactElement } from 'react'
import { expect } from 'vitest'

export function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

  return { ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>), queryClient: client }
}

export type Route = (path: string, init?: RequestInit) => unknown

/** Answers each call from the first route whose method+path prefix matches; anything else throws like a 404 would. */
export function routeApi(routes: Record<string, Route>): (path: string, init?: RequestInit) => Promise<unknown> {
  return async (path, init) => {
    const method = (init?.method ?? 'GET').toUpperCase()

    for (const [key, handler] of Object.entries(routes)) {
      const [m, prefix] = key.split(' ')

      if (m === method && path.startsWith(prefix)) {
        return handler(path, init)
      }
    }

    throw new Error(`No route for ${method} ${path}`)
  }
}

/** An empty notebook opens the "Add sources" prompt over the page; close it so the page itself can be queried. */
export async function dismissAddSources() {
  const dialog = await screen.findByRole('dialog', { name: 'Add sources' })

  fireEvent.keyDown(dialog, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
}
