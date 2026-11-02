import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $session } from '@/lib/harvis-session'
import { $busy } from '@/store/session'

import { type ArtStore } from './island-art'
import { IslandHost } from './island-host'

const fetchBots = vi.hoisted(() => vi.fn())
const startBotChat = vi.hoisted(() => vi.fn())
vi.mock('@/plugins/hermes-bots/data', async () => {
  const { useQuery } = await import('@tanstack/react-query')
  return { useRoster: (accountId: string) => useQuery({ queryKey: ['test-roster', accountId], queryFn: async () => ({ profiles: await fetchBots() }) }) }
})
vi.mock('@/plugins/hermes-bots/roster-actions', () => ({ openRosterBot: startBotChat }))

/** Records every mounted island and answers art offers; tests steer it via `mounts`. */
const mounts = vi.hoisted(() => ({ instances: [] as MountRecord[] }))

interface MountRecord {
  calls: [string, unknown][]
  disposed: boolean
  opts: { interactive?: boolean; onSelect?: (id: string) => void }
  root: HTMLElement
  clearArt: ReturnType<typeof vi.fn>
  dispose: ReturnType<typeof vi.fn>
  pause: ReturnType<typeof vi.fn>
  resume: ReturnType<typeof vi.fn>
  setInteractive: ReturnType<typeof vi.fn>
  setLowFx: ReturnType<typeof vi.fn>
  setSession: ReturnType<typeof vi.fn>
  setTheme: ReturnType<typeof vi.fn>
  useArt: ReturnType<typeof vi.fn>
}

vi.mock('@/island/mount.js', () => ({
  mountIsland: (root: HTMLElement, opts: MountRecord['opts']) => {
    const app: MountRecord = {
      calls: [],
      disposed: false,
      opts,
      root,
      clearArt: vi.fn(() => {
        app.calls.push(['clearArt', undefined])

        return { custom: false, message: '', state: 'builtin' }
      }),
      dispose: vi.fn(() => {
        app.disposed = true
        root.innerHTML = ''
      }),
      pause: vi.fn(() => app.calls.push(['pause', undefined])),
      resume: vi.fn(() => app.calls.push(['resume', undefined])),
      setInteractive: vi.fn(),
      setLowFx: vi.fn((on: boolean) => app.calls.push(['lowfx', on])),
      setSession: vi.fn((agents: unknown) => app.calls.push(['session', agents])),
      setTheme: vi.fn((theme: unknown) => app.calls.push(['theme', theme])),
      useArt: vi.fn(async (files: unknown) => {
        app.calls.push(['useArt', files])

        return { custom: true, message: '', state: 'custom' }
      })
    }

    mounts.instances.push(app)

    return app
  }
}))

const store = vi.hoisted(() => ({ clear: vi.fn(), load: vi.fn(), save: vi.fn() }))
const storeFor = vi.hoisted(() => vi.fn(() => store))

vi.mock('./island-art', async importOriginal => ({
  ...(await importOriginal<typeof import('./island-art')>()),
  accountArtStore: storeFor
}))

type ObserverCallback = (entries: { isIntersecting: boolean }[]) => void

let observe: ObserverCallback | null = null
let hidden = false

const setHidden = (value: boolean) => {
  hidden = value
  document.dispatchEvent(new Event('visibilitychange'))
}

const signIn = (id: string) =>
  $session.set({ status: 'signed-in', user: { id, email: '', name: '', role: 'user' } })

const botsOf = (...ids: string[]) => ids.map(id => ({ name: `Bot ${id}`, connectionId: 'local' }))

const lastMount = () => mounts.instances.at(-1) as MountRecord
const mountNode = (container: HTMLElement) => container.querySelector('.group\\/island > div')
const lastSession = () => (lastMount().setSession.mock.calls.at(-1)?.[0] ?? []) as { id: string; name: string }[]
const waitForResidents = (ids: string[]) => waitFor(() => expect(lastSession().map(a => a.name)).toEqual(ids))

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(<QueryClientProvider client={client}><IslandHost /></QueryClientProvider>)

  return { view }
}

beforeEach(() => {
  hidden = false
  observe = null
  mounts.instances.length = 0
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(cb: ObserverCallback) {
        observe = cb
      }

      observe() {}
      disconnect() {}
    }
  )
  $busy.set(false)
  signIn('test-user')
  fetchBots.mockReset().mockResolvedValue([])
  startBotChat.mockReset().mockResolvedValue('sid-1')
  storeFor.mockClear()
  store.clear.mockReset().mockResolvedValue(undefined)
  store.save.mockReset().mockResolvedValue(undefined)
  store.load.mockReset().mockResolvedValue(null)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  $session.set({ status: 'signed-out', expired: false })
})

describe('IslandHost rendering', () => {
  it('mounts the island in-page: no iframe, no postMessage target', () => {
    const { view } = mount()

    expect(mounts.instances).toHaveLength(1)
    expect(view.container.querySelector('iframe')).toBeNull()
    expect(mountNode(view.container)).toBe(lastMount().root)
  })

  it('explores fullscreen and returns to the faded chat background', () => {
    const { view } = mount()
    const mountDiv = () => view.container.querySelector('.group\\/island > div') as HTMLElement

    // Faded state: zoomed in and feathered into the chat surface.
    expect(mountDiv().className).toContain('opacity-25')
    expect(mountDiv().className).toContain('scale-[1.75]')
    expect(mountDiv().className).toContain('mask-image')
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }))
    // Explore stays in place (no portal) so the zoom-out transition can run; it remounts.
    expect(mounts.instances).toHaveLength(2)
    expect(mounts.instances[0].disposed).toBe(true)
    expect(mountDiv().className).toContain('opacity-100')
    expect(mountDiv().className).not.toContain('mask-image')
    expect(screen.getByRole('button', { name: 'Back to bots' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Back to bots' }))
    expect(mounts.instances[1].disposed).toBe(true)
    expect(mountDiv().className).toContain('opacity-25')
  })

  it('shows the account bots as island residents, and selects one into a chat', async () => {
    fetchBots.mockResolvedValue(botsOf('bot-a', 'bot-b'))
    mount()

    await waitForResidents(['Bot bot-a', 'Bot bot-b'])

    act(() => lastMount().opts.onSelect?.(lastSession()[1].id))
    expect(startBotChat).toHaveBeenCalledWith(botsOf('bot-b')[0], expect.objectContaining({ isCurrent: expect.any(Function) }))
    act(() => lastMount().opts.onSelect?.('unknown'))
    expect(startBotChat).toHaveBeenCalledTimes(1)
  })
})

describe('IslandHost roster stability', () => {
  it('keeps in-flight bot opens alive across a same-user session re-probe', async () => {
    fetchBots.mockResolvedValue(botsOf('bot-a'))
    mount()
    await waitForResidents(['Bot bot-a'])
    act(() => lastMount().opts.onSelect?.(lastSession()[0].id))
    const guard = startBotChat.mock.calls[0][1].isCurrent as () => boolean

    act(() => signIn('test-user'))
    expect(guard()).toBe(true)
    act(() => $session.set({ status: 'signed-out', expired: false }))
    expect(guard()).toBe(false)
  })

  it('does not rebuild the island when a roster poll returns the same bots', async () => {
    fetchBots.mockResolvedValue(botsOf('bot-a'))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><IslandHost /></QueryClientProvider>)
    await waitForResidents(['Bot bot-a'])
    const mount0 = lastMount()
    const before = mount0.setSession.mock.calls.length

    await act(() => client.invalidateQueries({ queryKey: ['test-roster', 'test-user'] }))
    await waitFor(() => expect(fetchBots.mock.calls.length).toBeGreaterThan(1))
    expect(mount0.setSession.mock.calls.length).toBe(before)

    fetchBots.mockResolvedValue(botsOf('bot-a', 'bot-b'))
    await act(() => client.invalidateQueries({ queryKey: ['test-roster', 'test-user'] }))
    await waitForResidents(['Bot bot-a', 'Bot bot-b'])
  })
})

describe('IslandHost account isolation', () => {
  it('disposes the old island on account switch and shows only the new account bots', async () => {
    fetchBots.mockImplementation(async () => botsOf(`bot-${$session.get().status === 'signed-in' ? ($session.get() as never as { user: { id: string } }).user.id : 'none'}`))
    const { view } = mount()
    await waitForResidents(['Bot bot-test-user'])
    const first = lastMount()
    const oldId = lastSession()[0].id
    act(() => first.opts.onSelect?.(oldId))
    const guard = startBotChat.mock.calls[0][1].isCurrent as () => boolean
    expect(guard()).toBe(true)

    act(() => signIn('other-user'))
    await waitFor(() => expect(mounts.instances).toHaveLength(2))
    await waitForResidents(['Bot bot-other-user'])

    expect(first.disposed).toBe(true)
    expect(guard()).toBe(false)
    act(() => first.opts.onSelect?.(oldId))
    expect(startBotChat).toHaveBeenCalledTimes(1)
    expect(first.root.isConnected).toBe(false)
    expect(view.container.querySelectorAll('.group\\/island')).toHaveLength(1)
  })

  it('keeps art per account and restores it on mount', async () => {
    store.load.mockResolvedValue({ 'Maps/Town.tbin': new Uint8Array([1]).buffer })
    mount()
    await waitFor(() => expect(lastMount().useArt).toHaveBeenCalled())

    expect(storeFor).toHaveBeenCalledWith('test-user')
    await act(async () => undefined)
    expect(store.save).not.toHaveBeenCalled() // a restore is not written back

    act(() => signIn('other-user'))
    await waitFor(() => expect(mounts.instances).toHaveLength(2))
    expect(storeFor).toHaveBeenCalledWith('other-user')
  })

  it('unmounts the island on sign-out', () => {
    const { view } = mount()

    act(() => $session.set({ status: 'signed-out', expired: false }))

    expect(view.container.querySelector('.group\\/island')).toBeNull()
    expect(lastMount().disposed).toBe(true)
  })
})

describe('IslandHost lifecycle wiring', () => {
  it('a run starting turns lowfx on, a run ending turns it off', () => {
    mount()

    act(() => $busy.set(true))
    expect(lastMount().setLowFx).toHaveBeenLastCalledWith(true)

    act(() => $busy.set(false))
    expect(lastMount().setLowFx).toHaveBeenLastCalledWith(false)
  })

  it('sends the app theme to the island', () => {
    mount()

    const theme = lastMount().setTheme.mock.calls.at(-1)?.[0] as { colors: Record<string, string>; mode: string }

    expect(theme.mode).toMatch(/^(dark|light)$/)
    expect(Object.keys(theme.colors).sort()).toEqual(['background', 'border', 'foreground', 'mutedForeground', 'popover', 'primary', 'primaryForeground'])
  })

  it('pauses when the document is hidden and resumes when it is visible again', () => {
    mount()

    act(() => setHidden(true))
    expect(lastMount().pause).toHaveBeenCalled()
    act(() => setHidden(false))
    expect(lastMount().resume).toHaveBeenCalled()
  })

  it('pauses when scrolled out of view and resumes when scrolled back', () => {
    mount()

    act(() => observe?.([{ isIntersecting: false }]))
    expect(lastMount().pause).toHaveBeenCalled()
    act(() => observe?.([{ isIntersecting: true }]))
    expect(lastMount().resume).toHaveBeenCalled()
  })

  it('disposes the island when it unmounts', () => {
    const { view } = mount()

    view.unmount()

    expect(lastMount().disposed).toBe(true)
    expect(lastMount().root.innerHTML).toBe('')
  })
})

describe('IslandHost art controls', () => {
  it('offers the picked folder to the island and saves it once shown', async () => {
    mount()
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }))

    const input = document.querySelector('input[type=file]') as HTMLInputElement
    expect(input).not.toBeNull()
    expect(screen.getByRole('button', { name: 'Use my game art' })).toBeTruthy()

    const file = new File([new Uint8Array(4)], 'Cursors.png')
    Object.defineProperty(file, 'webkitRelativePath', { value: 'out/LooseSprites/Cursors.png' })
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => expect(lastMount().useArt).toHaveBeenCalled())
    await waitFor(() => expect(store.save).toHaveBeenCalled())
    fireEvent.click(await screen.findByRole('button', { name: 'Use built-in art' }))
    expect(lastMount().clearArt).toHaveBeenCalled()
    expect(store.clear).toHaveBeenCalled()
  })

  it('ignores spoofed island messages: nothing listens to postMessage', async () => {
    fetchBots.mockResolvedValue(botsOf('bot-a'))
    mount()
    await waitForResidents(['Bot bot-a'])
    const before = lastMount().calls.length

    act(() => window.dispatchEvent(new MessageEvent('message', {
      data: { agentId: 'bot-a', type: 'island:select' }, origin: window.location.origin
    })))
    act(() => window.dispatchEvent(new MessageEvent('message', {
      data: { message: 'spoofed', state: 'error', type: 'island:stardew-status' }, origin: 'null'
    })))
    await act(async () => undefined)

    expect(lastMount().calls.length).toBe(before)
    expect(startBotChat).not.toHaveBeenCalled()
    expect(store.clear).not.toHaveBeenCalled()
  })
})
