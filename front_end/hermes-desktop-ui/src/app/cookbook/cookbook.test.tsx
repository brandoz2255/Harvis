import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $session } from '@/lib/harvis-session'
import { $confirmRequest, settleConfirm } from '@/store/confirm'

import type { CookbookNode } from '../settings/harvis-api'

import { CookbookView } from '.'

const main: CookbookNode = {
  alive: true,
  latency_ms: 4,
  llmfit_url: 'http://llmfit:8787',
  name: 'main-host',
  role: 'main'
}
const gaming: CookbookNode = {
  alive: true,
  latency_ms: 9,
  llmfit_url: 'http://gaming-pc.local:8787',
  name: 'Gaming PC',
  role: 'subhost'
}

const systems: Record<string, object> = {
  'Gaming PC': { cpu_cores: 16, gpu_name: 'RTX 4090', gpu_vram_gb: 24, total_ram_gb: 64 },
  'main-host': { cpu_cores: 8, gpu_name: 'RX 7600', gpu_vram_gb: 8, total_ram_gb: 32 }
}

const fit = [
  {
    fit_level: 'perfect',
    name: 'Qwen/Qwen3-8B',
    ollama_tag: 'qwen3:8b',
    best_quant: 'Q4_K_M',
    memory_required_gb: 5.2
  },
  { fit_level: 'good', name: 'org/Odd-Model-GGUF', best_quant: 'Q5_K_M' },
  { downloadable: false, name: 'org/Big-AWQ', reason: 'Needs a GPU server.' }
]

let nodes: CookbookNode[] = [main, gaming]
let calls: { body: unknown; method: string; path: string }[] = []
let reply: Record<string, { body: unknown; status: number }> = {}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' }, status })

const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
  const method = init?.method ?? 'GET'
  calls.push({ body: init?.body ? JSON.parse(String(init.body)) : undefined, method, path })

  const key = `${method} ${path.split('?')[0]}`

  if (reply[key]) {
    return json(reply[key].body, reply[key].status)
  }

  if (key === 'GET /api/cookbook/nodes') {
    return json({ nodes })
  }

  if (key === 'GET /api/cookbook/system') {
    const name = new URL(path, 'http://x').searchParams.get('node') ?? ''

    return json({ system: systems[name] })
  }

  if (key === 'GET /api/cookbook/installed') {
    return json({ models: [{ name: 'gemma3:4b', size: 3_300_000_000 }] })
  }

  if (key === 'GET /api/cookbook/recommend' || key === 'GET /api/cookbook/models') {
    return json({ models: fit })
  }

  return json({ detail: 'not mocked' }, 404)
})

const user = (role: string) => ({ status: 'signed-in' as const, user: { email: 'a@b.test', id: '1', name: 'A', role } })

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(
    <QueryClientProvider client={client}>
      <CookbookView />
    </QueryClientProvider>
  )
}

const callsTo = (method: string, prefix: string) => calls.filter(c => c.method === method && c.path.startsWith(prefix))

beforeEach(() => {
  nodes = [main, gaming]
  calls = []
  reply = {}
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  settleConfirm(false)
  fetchMock.mockClear()
  vi.unstubAllGlobals()
  $session.set({ status: 'checking' })
})

describe('Cookbook page', () => {
  it('lists every computer with its hardware, what is installed, and what fits', async () => {
    $session.set(user('admin'))
    renderPage()

    await screen.findByTestId('cookbook-node-main-host')
    expect(screen.getByTestId('cookbook-node-Gaming PC')).toBeTruthy()

    // Hardware is read for each computer, not just the selected one.
    await screen.findByText('RTX 4090 · 24 GB video memory')
    expect(screen.getByText('RX 7600 · 8 GB video memory')).toBeTruthy()
    expect(
      callsTo('GET', '/api/cookbook/system')
        .map(c => c.path)
        .sort()
    ).toEqual(['/api/cookbook/system?node=Gaming%20PC', '/api/cookbook/system?node=main-host'])

    // The server's own computer is selected first.
    await screen.findByText('gemma3:4b')
    await screen.findByText('Qwen/Qwen3-8B')
    expect(screen.getByText('Fits easily')).toBeTruthy()
    expect(screen.getByText('Installed on main-host')).toBeTruthy()
    expect(callsTo('GET', '/api/cookbook/recommend')[0].path).toContain('node=main-host')
  })

  it('shows the models for the computer you pick', async () => {
    $session.set(user('admin'))
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')
    fireEvent.click(screen.getByText('Gaming PC'))

    await screen.findByText('Installed on Gaming PC')
    await waitFor(() =>
      expect(callsTo('GET', '/api/cookbook/recommend').some(c => c.path.includes('node=Gaming+PC'))).toBe(true)
    )
  })
})

describe('admin and non-admin controls', () => {
  it('gives an admin Download buttons, Add, and Remove for added computers only', async () => {
    $session.set(user('admin'))
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')

    expect(screen.getAllByRole('button', { name: 'Download' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Request' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Add a computer' })).toBeTruthy()
    // One Remove: the Gaming PC. The server's own entry has none.
    expect(screen.getAllByRole('button', { name: 'Remove' })).toHaveLength(1)
    // Addresses are an admin's to see.
    expect(screen.getByText('http://gaming-pc.local:8787')).toBeTruthy()
  })

  it('hides Remove on any node the server marks built-in, not only the main one', async () => {
    $session.set(user('admin'))
    nodes = [main, { ...gaming, builtin: true }]
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')

    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull()
  })

  it('still offers Remove on an added node the server marks as not built-in', async () => {
    $session.set(user('admin'))
    nodes = [
      { ...main, builtin: true },
      { ...gaming, builtin: false }
    ]
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')

    expect(screen.getAllByRole('button', { name: 'Remove' })).toHaveLength(1)
  })

  it('gives everyone else Request buttons and no way to add, remove, or download', async () => {
    $session.set(user('user'))
    nodes = [
      { ...main, llmfit_url: null },
      { ...gaming, llmfit_url: null }
    ]
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')

    expect(screen.queryByRole('button', { name: 'Download' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Add a computer' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull()
    expect(screen.queryByText('http://gaming-pc.local:8787')).toBeNull()

    const requests = screen.getAllByRole('button', { name: 'Request' }) as HTMLButtonElement[]
    // Only the model with an Ollama name can be asked for; the odd one and the GPU-server one cannot.
    expect(requests.filter(b => !b.disabled)).toHaveLength(1)
  })

  it('sends a non-admin request for the Ollama name', async () => {
    $session.set(user('user'))
    reply['POST /api/model-requests'] = { body: { request: { id: 1 } }, status: 201 }
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')
    fireEvent.click((screen.getAllByRole('button', { name: 'Request' }) as HTMLButtonElement[]).find(b => !b.disabled)!)

    await screen.findByRole('button', { name: 'Requested' })
    expect(callsTo('POST', '/api/model-requests')[0].body).toEqual({ model: 'qwen3:8b' })
    expect(callsTo('POST', '/api/cookbook/download')).toHaveLength(0)
  })
})

describe('adding and removing computers', () => {
  it('adds a computer and sends only the fields that were filled in', async () => {
    $session.set(user('admin'))
    reply['POST /api/cookbook/nodes'] = { body: { ...gaming, name: 'Laptop' }, status: 200 }
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')
    fireEvent.click(screen.getByRole('button', { name: 'Add a computer' }))
    fireEvent.change(screen.getByPlaceholderText('Gaming PC'), { target: { value: 'Laptop' } })
    fireEvent.change(screen.getByPlaceholderText('http://gaming-pc.local:8787'), {
      target: { value: 'laptop.local:8787' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Add computer' }))

    await waitFor(() => expect(callsTo('POST', '/api/cookbook/nodes')).toHaveLength(1))
    expect(callsTo('POST', '/api/cookbook/nodes')[0].body).toEqual({ llmfit_url: 'laptop.local:8787', name: 'Laptop' })
    // The list is read again so the new computer shows up.
    await waitFor(() => expect(callsTo('GET', '/api/cookbook/nodes').length).toBeGreaterThan(1))
  })

  it("shows the server's sentence when llmfit does not answer at that address", async () => {
    $session.set(user('admin'))
    const detail = 'llmfit at http://nowhere:8787 did not respond. Start `llmfit serve` on that machine.'
    reply['POST /api/cookbook/nodes'] = { body: { detail }, status: 422 }
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')
    fireEvent.click(screen.getByRole('button', { name: 'Add a computer' }))
    fireEvent.change(screen.getByPlaceholderText('Gaming PC'), { target: { value: 'Ghost' } })
    fireEvent.change(screen.getByPlaceholderText('http://gaming-pc.local:8787'), { target: { value: 'nowhere:8787' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add computer' }))

    expect((await screen.findByRole('alert')).textContent).toBe(detail)
  })

  it('removes a computer only after the admin confirms', async () => {
    $session.set(user('admin'))
    reply['DELETE /api/cookbook/nodes/Gaming%20PC'] = { body: { removed: 'Gaming PC' }, status: 200 }
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect($confirmRequest.get()?.title).toBe('Remove Gaming PC?'))
    expect(callsTo('DELETE', '/api/cookbook/nodes')).toHaveLength(0)

    settleConfirm(true)

    await waitFor(() => expect(callsTo('DELETE', '/api/cookbook/nodes/Gaming%20PC')).toHaveLength(1))
  })

  it('does not remove anything when the admin says no', async () => {
    $session.set(user('admin'))
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect($confirmRequest.get()).not.toBeNull())
    settleConfirm(false)

    await Promise.resolve()
    expect(callsTo('DELETE', '/api/cookbook/nodes')).toHaveLength(0)
  })
})

describe('downloading', () => {
  it('shows live progress from the stream, then says it is done', async () => {
    $session.set(user('admin'))
    const enc = new TextEncoder()
    let push: (event: object) => void = () => {}
    let close: () => void = () => {}

    reply = {}
    const base = fetchMock.getMockImplementation()!

    fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/api/cookbook/download') {
        calls.push({ body: JSON.parse(String(init?.body)), method: 'POST', path })

        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              push = event => controller.enqueue(enc.encode(`data: ${JSON.stringify(event)}\n\n`))
              close = () => controller.close()
            }
          }),
          { status: 200 }
        )
      }

      return base(path, init)
    })

    renderPage()
    await screen.findByText('Qwen/Qwen3-8B')

    const row = screen.getByText('Qwen/Qwen3-8B').closest('.\\@container') as HTMLElement
    fireEvent.click(row.querySelector('button') as HTMLButtonElement)

    await waitFor(() => expect(callsTo('POST', '/api/cookbook/download')).toHaveLength(1))
    expect(callsTo('POST', '/api/cookbook/download')[0].body).toEqual({ node: 'main-host', ollama_tag: 'qwen3:8b' })

    push({ completed: 500, digest: 'sha256:a', status: 'pulling a', total: 1000 })
    await screen.findByText('50%')
    expect(screen.getByTestId('model-download').textContent).toContain('qwen3:8b')

    // Only one at a time: the other Download buttons are off while this one runs.
    expect((screen.getAllByRole('button', { name: 'Download' }) as HTMLButtonElement[]).every(b => b.disabled)).toBe(
      true
    )

    push({ status: 'success' })
    push({ final: true, status: 'done' })
    close()

    await screen.findByText('Downloaded. It is in the list above.')
  })

  it("shows the server's refusal as the download's message", async () => {
    $session.set(user('admin'))
    const base = fetchMock.getMockImplementation()!

    fetchMock.mockImplementation(async (path: string, init?: RequestInit) =>
      path === '/api/cookbook/download' ? json({ detail: 'Node has no ollama url configured.' }, 400) : base(path, init)
    )

    renderPage()
    await screen.findByText('Qwen/Qwen3-8B')

    const row = screen.getByText('Qwen/Qwen3-8B').closest('.\\@container') as HTMLElement
    fireEvent.click(row.querySelector('button') as HTMLButtonElement)

    expect((await screen.findByRole('alert')).textContent).toBe('Node has no ollama url configured.')
  })
})

describe('when llmfit is not running', () => {
  const down: CookbookNode = {
    alive: false,
    error: 'All connection attempts failed',
    latency_ms: null,
    name: 'main-host',
    role: 'main'
  }

  it('says so, quotes the server, and says what to do instead of loading', async () => {
    $session.set(user('admin'))
    nodes = [down]
    renderPage()

    await screen.findByText('llmfit is not running on main-host')
    expect(screen.getByText('The server said: All connection attempts failed')).toBeTruthy()
    expect(screen.getByText(/runs as the/).textContent).toContain('llmfit service in the Docker setup')
    expect(screen.getByRole('button', { name: 'Check again', hidden: false })).toBeTruthy()

    // Nothing is asked of a machine that cannot answer, and no spinner is left behind.
    expect(callsTo('GET', '/api/cookbook/recommend')).toHaveLength(0)
    expect(callsTo('GET', '/api/cookbook/system')).toHaveLength(0)
    expect(callsTo('GET', '/api/cookbook/installed')).toHaveLength(0)
    expect(screen.queryByRole('status', { name: /loading/i })).toBeNull()
  })

  it('tells an added computer how to start llmfit, and tells a non-admin to ask the admin', async () => {
    $session.set(user('admin'))
    nodes = [main, { ...down, name: 'Gaming PC', role: 'subhost' }]
    renderPage()

    await screen.findByText('Qwen/Qwen3-8B')
    fireEvent.click(screen.getByText('Gaming PC'))
    await screen.findByText('llmfit is not running on Gaming PC')
    expect(screen.getByText(/llmfit serve --host 0.0.0.0 --port 8787/)).toBeTruthy()

    cleanup()
    $session.set(user('user'))
    nodes = [{ ...down, llmfit_url: null }]
    renderPage()

    await screen.findByText('Ask the admin to start it.')
  })

  it('asks again when Check again is pressed', async () => {
    $session.set(user('admin'))
    nodes = [down]
    renderPage()

    await screen.findByText('llmfit is not running on main-host')
    const before = callsTo('GET', '/api/cookbook/nodes').length

    nodes = [main]
    fireEvent.click(screen.getAllByRole('button', { name: 'Check again' })[0])

    await screen.findByText('Qwen/Qwen3-8B')
    expect(callsTo('GET', '/api/cookbook/nodes').length).toBeGreaterThan(before)
  })

  it('shows the error when the list of computers itself cannot be loaded', async () => {
    $session.set(user('admin'))
    reply['GET /api/cookbook/nodes'] = { body: { detail: 'Sign in to continue.' }, status: 500 }
    renderPage()

    await screen.findByText(/Could not load the list of computers\. Sign in to continue\./)
  })
})
