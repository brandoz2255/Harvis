import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { stubResizeObserver } from '@/test/jsdom'

const { harvisApi, notify, openPreview } = vi.hoisted(() => ({
  harvisApi: vi.fn(),
  notify: vi.fn(),
  openPreview: vi.fn()
}))

vi.mock('./api', () => ({ harvisApi }))
vi.mock('@/store/preview', () => ({ openPreview }))
vi.mock('@hermes/plugin-sdk', async importOriginal => {
  const actual = await importOriginal<typeof import('@hermes/plugin-sdk')>()
  const { atom } = await import('nanostores')

  return {
    ...actual,
    host: {
      ...actual.host,
      notify,
      state: { ...actual.host.state, busy: atom(false), focusedStoredSessionId: atom('sess-1') }
    }
  }
})

const { SandboxButton } = await import('./sandbox-button')

const info = (over = {}) => ({
  cwd: '/sandbox/sess-1/workspace',
  size_bytes: 3 * 1024 ** 3,
  warn_bytes: 20 * 1024 ** 3,
  over_warn: false,
  gpu: false,
  gpu_available: true,
  running: true,
  apps: [
    { port: 7860, public: true, url: '/hermes-api/sandbox-app/7.sess-1.abc/7860/' },
    { port: 9000, public: false, url: '/hermes-api/sandbox-app/7.sess-1.abc/9000/' }
  ],
  ...over
})

function renderButton() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(
    <QueryClientProvider client={client}>
      <SandboxButton />
    </QueryClientProvider>
  )
}

beforeAll(() => stubResizeObserver())

beforeEach(() => {
  harvisApi.mockReset()
  notify.mockReset()
  openPreview.mockReset()
})

afterEach(cleanup)

describe('SandboxButton', () => {
  it('shows size, apps and opens one in the right panel', async () => {
    harvisApi.mockResolvedValue(info())
    renderButton()

    fireEvent.click(await screen.findByRole('button', { name: "This chat's sandbox" }))
    expect(await screen.findByText('3.0 GB')).toBeTruthy()
    expect(screen.getByText('localhost only')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Open' }))
    expect(openPreview).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'url', url: `${window.location.origin}/hermes-api/sandbox-app/7.sess-1.abc/7860/` })
    )
    expect(harvisApi).toHaveBeenCalledWith('/hermes-api/api/sandbox/info?session=sess-1')
  })

  it('switches the GPU on through the API', async () => {
    harvisApi.mockImplementation(async (path: string) => (path.includes('/gpu') ? { ok: true } : info()))
    renderButton()

    fireEvent.click(await screen.findByRole('button', { name: "This chat's sandbox" }))
    fireEvent.click(await screen.findByRole('switch'))
    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        '/hermes-api/api/sandbox/gpu',
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ session: 'sess-1', on: true }) })
      )
    )
  })

  it('pops a toast when a new app starts serving', async () => {
    harvisApi.mockResolvedValueOnce(info({ apps: [] }))
    const view = renderButton()
    await screen.findByRole('button', { name: "This chat's sandbox" })
    expect(notify).not.toHaveBeenCalled()

    harvisApi.mockResolvedValue(info())
    fireEvent.click(screen.getByRole('button', { name: "This chat's sandbox" })) // open → faster refetch
    await waitFor(() => expect(notify).toHaveBeenCalledTimes(1), { timeout: 8000 })
    expect(notify.mock.calls[0][0]).toMatchObject({ title: 'App ready in the sandbox', action: { label: 'Open' } })
    view.unmount()
  }, 10_000)

  it('stays hidden when the sandbox is off', async () => {
    harvisApi.mockResolvedValue(info({ cwd: null }))
    renderButton()
    await waitFor(() => expect(harvisApi).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: "This chat's sandbox" })).toBeNull()
  })
})
