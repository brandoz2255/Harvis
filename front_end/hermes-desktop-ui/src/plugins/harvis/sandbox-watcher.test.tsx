import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { atom } from 'nanostores'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { busy, harvisApi, notify, openPreview, setFileBrowserOpen } = vi.hoisted(() => ({
  busy: { current: null as null | ReturnType<typeof atom<boolean>> },
  harvisApi: vi.fn(),
  notify: vi.fn(),
  openPreview: vi.fn(),
  setFileBrowserOpen: vi.fn()
}))

vi.mock('./api', () => ({ harvisApi }))
vi.mock('@/store/preview', () => ({ openPreview }))
vi.mock('@/store/layout', () => ({ setFileBrowserOpen }))
vi.mock('@hermes/plugin-sdk', async importOriginal => {
  const actual = await importOriginal<typeof import('@hermes/plugin-sdk')>()
  const { atom: makeAtom } = await import('nanostores')

  busy.current = makeAtom(false)

  return {
    ...actual,
    host: {
      ...actual.host,
      notify,
      state: { ...actual.host.state, busy: busy.current, focusedStoredSessionId: makeAtom('sess-1') }
    }
  }
})

const { SandboxWatcher } = await import('./sandbox-watcher')

const info = (over = {}) => ({
  cwd: '/sandbox/sess-1/workspace',
  size_bytes: 1024,
  warn_bytes: 20 * 1024 ** 3,
  over_warn: false,
  gpu: false,
  gpu_available: false,
  running: true,
  apps: [
    { port: 7860, public: true, url: '/hermes-api/sandbox-app/7.sess-1.abc/7860/' },
    { port: 9000, public: false, url: '/hermes-api/sandbox-app/7.sess-1.abc/9000/' }
  ],
  ...over
})

function renderWatcher() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(
    <QueryClientProvider client={client}>
      <SandboxWatcher />
    </QueryClientProvider>
  )
}

beforeEach(() => {
  harvisApi.mockReset()
  notify.mockReset()
  openPreview.mockReset()
  setFileBrowserOpen.mockReset()
  window.localStorage.clear()
  busy.current?.set(false)
})

afterEach(cleanup)

describe('SandboxWatcher', () => {
  it('starts the sandbox by asking for it, shows nothing, and opens the Files pane once', async () => {
    harvisApi.mockResolvedValue(info())
    const view = renderWatcher()

    await waitFor(() => expect(setFileBrowserOpen).toHaveBeenCalledWith(true))
    expect(harvisApi).toHaveBeenCalledWith('/hermes-api/api/sandbox/info?session=sess-1')
    expect(view.container.innerHTML).toBe('')
    view.unmount()

    renderWatcher()
    await waitFor(() => expect(harvisApi).toHaveBeenCalledTimes(2))
    expect(setFileBrowserOpen).toHaveBeenCalledTimes(1)
  })

  it('pops a toast with Open when a new app starts serving', async () => {
    harvisApi.mockResolvedValueOnce(info({ apps: [] }))
    const view = renderWatcher()
    await waitFor(() => expect(harvisApi).toHaveBeenCalledTimes(1))
    expect(notify).not.toHaveBeenCalled()

    harvisApi.mockResolvedValue(info())
    act(() => busy.current?.set(true)) // a turn running → faster refetch
    await waitFor(() => expect(notify).toHaveBeenCalledTimes(1), { timeout: 8000 })

    const toast = notify.mock.calls[0][0]
    expect(toast).toMatchObject({ title: 'App ready in the sandbox', action: { label: 'Open' } })
    toast.action.onClick()
    expect(openPreview).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'url',
        url: `${window.location.origin}/hermes-api/sandbox-app/7.sess-1.abc/7860/`
      })
    )
    view.unmount()
  }, 10_000)

  it('leaves the Files pane alone when there is no sandbox', async () => {
    harvisApi.mockResolvedValue(info({ cwd: null }))
    renderWatcher()
    await waitFor(() => expect(harvisApi).toHaveBeenCalled())
    expect(setFileBrowserOpen).not.toHaveBeenCalled()
  })
})
