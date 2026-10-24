import { readFileSync } from 'node:fs'

import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  artifactDataKey,
  ASK_ENDPOINT,
  askHarvis,
  ASK_WINDOW_MS,
  bridgeRequestFromMessage,
  bridgeStubScript,
  bridgeTransportScript,
  createBridgeHost,
  MAX_ASK_PROMPT,
  MAX_ASKS_PER_MINUTE,
  MAX_DATA_BYTES,
  REQUEST_MESSAGE_TYPE,
  RESPONSE_MESSAGE_TYPE,
  withArtifactBridge
} from './artifact-bridge'

const reportUnauthorized = vi.hoisted(() => vi.fn())

vi.mock('@/lib/harvis-session', () => ({ reportUnauthorized }))

const TOKEN = 'tok'

interface FakeFrame {
  postMessage: ReturnType<typeof vi.fn>
}

const fakeFrame = (): FakeFrame => ({ postMessage: vi.fn() })

function memoryStorage() {
  const items = new Map<string, string>()

  return {
    getItem: (key: string) => items.get(key) ?? null,
    items,
    setItem: (key: string, value: string) => {
      items.set(key, value)
    }
  }
}

const request = (over: Record<string, unknown> = {}) => ({
  id: 1,
  op: 'ask',
  prompt: 'tell me a joke',
  token: TOKEN,
  type: REQUEST_MESSAGE_TYPE,
  ...over
})

function setup(over: Partial<Parameters<typeof createBridgeHost>[0]> = {}) {
  const frame = fakeFrame()
  const storage = memoryStorage()
  const ask = vi.fn(async (prompt: string) => `answer to: ${prompt}`)

  const host = createBridgeHost({
    ask,
    contentKey: () => 'page-a',
    frame: () => frame,
    storage,
    token: TOKEN,
    ...over
  })

  const send = (data: unknown, source: unknown = frame) => host.handle({ data, source })

  const lastReply = () => frame.postMessage.mock.calls.at(-1)?.[0] as Record<string, unknown>

  return { ask, frame, host, lastReply, send, storage }
}

describe('bridgeRequestFromMessage', () => {
  it('accepts our type with our token and a known op', () => {
    expect(bridgeRequestFromMessage(request(), TOKEN)?.op).toBe('ask')
    expect(bridgeRequestFromMessage(request({ op: 'load', key: 'k' }), TOKEN)?.key).toBe('k')
  })

  it('rejects wrong token, wrong type, unknown op, bad id and hostile shapes', () => {
    expect(bridgeRequestFromMessage(request({ token: 'stolen' }), TOKEN)).toBeNull()
    expect(bridgeRequestFromMessage(request({ type: 'hermes-inline-preview-intent' }), TOKEN)).toBeNull()
    expect(bridgeRequestFromMessage(request({ op: 'delete' }), TOKEN)).toBeNull()
    expect(bridgeRequestFromMessage(request({ id: 'one' }), TOKEN)).toBeNull()
    expect(bridgeRequestFromMessage(request({ id: Infinity }), TOKEN)).toBeNull()
    expect(bridgeRequestFromMessage(null, TOKEN)).toBeNull()
    expect(bridgeRequestFromMessage('ask', TOKEN)).toBeNull()
  })
})

describe('bridge host trust boundary', () => {
  it('ignores a message with a bad token: no model call, no reply', async () => {
    const { ask, frame, send } = setup()

    expect(await send(request({ token: 'stolen' }))).toBe(false)
    expect(ask).not.toHaveBeenCalled()
    expect(frame.postMessage).not.toHaveBeenCalled()
  })

  it('ignores a right-token message that came from some other window', async () => {
    const { ask, frame, send } = setup()

    expect(await send(request(), fakeFrame())).toBe(false)
    expect(await send(request(), null)).toBe(false)
    expect(ask).not.toHaveBeenCalled()
    expect(frame.postMessage).not.toHaveBeenCalled()
  })

  it('ignores everything while the frame is not mounted', async () => {
    const { ask, send } = setup({ frame: () => null })

    expect(await send(request(), null)).toBe(false)
    expect(ask).not.toHaveBeenCalled()
  })

  it('answers a valid ask on the frame that asked, with the request id and token', async () => {
    const { ask, frame, lastReply, send } = setup()

    expect(await send(request({ id: 7 }))).toBe(true)
    expect(ask).toHaveBeenCalledWith('tell me a joke')
    expect(frame.postMessage).toHaveBeenCalledTimes(1)
    expect(frame.postMessage.mock.calls[0]![1]).toBe('*')
    expect(lastReply()).toEqual({
      id: 7,
      ok: true,
      result: 'answer to: tell me a joke',
      token: TOKEN,
      type: RESPONSE_MESSAGE_TYPE
    })
  })

  it('hides an unexpected failure behind a plain message', async () => {
    const ask = vi.fn(async () => {
      throw new Error('secret stack detail at /srv/harvis')
    })

    const { lastReply, send } = setup({ ask })

    await send(request())

    expect(lastReply().ok).toBe(false)
    expect(String(lastReply().error)).not.toContain('secret')
  })
})

describe('askModel limits', () => {
  it('enforces the prompt cap without calling the model', async () => {
    const { ask, lastReply, send } = setup()

    await send(request({ prompt: 'x'.repeat(MAX_ASK_PROMPT + 1) }))

    expect(ask).not.toHaveBeenCalled()
    expect(lastReply().ok).toBe(false)
    expect(String(lastReply().error)).toContain(String(MAX_ASK_PROMPT))

    await send(request({ id: 2, prompt: 'x'.repeat(MAX_ASK_PROMPT) }))

    expect(ask).toHaveBeenCalledTimes(1)
    expect(lastReply().ok).toBe(true)
  })

  it('rejects an empty or missing prompt', async () => {
    const { ask, lastReply, send } = setup()

    await send(request({ prompt: '   ' }))
    expect(lastReply().ok).toBe(false)

    await send(request({ prompt: undefined }))
    expect(lastReply().ok).toBe(false)
    expect(ask).not.toHaveBeenCalled()
  })

  it('rejects the 11th call inside a minute, then allows one once the window moves on', async () => {
    let clock = 1_000_000
    const { ask, lastReply, send } = setup({ now: () => clock })

    for (let i = 0; i < MAX_ASKS_PER_MINUTE; i += 1) {
      await send(request({ id: i }))
      expect(lastReply().ok).toBe(true)
      clock += 100
    }

    await send(request({ id: 99 }))

    expect(lastReply()).toMatchObject({ id: 99, ok: false })
    expect(ask).toHaveBeenCalledTimes(MAX_ASKS_PER_MINUTE)

    clock += ASK_WINDOW_MS

    await send(request({ id: 100 }))

    expect(lastReply()).toMatchObject({ id: 100, ok: true })
    expect(ask).toHaveBeenCalledTimes(MAX_ASKS_PER_MINUTE + 1)
  })

  it('allows only one call in flight, and a refused call does not spend quota', async () => {
    let release: (text: string) => void = () => {}

    const ask = vi.fn(
      () =>
        new Promise<string>(resolve => {
          release = resolve
        })
    )

    const { frame, send } = setup({ ask })

    const first = send(request({ id: 1 }))
    await Promise.resolve()

    await send(request({ id: 2 }))

    expect(ask).toHaveBeenCalledTimes(1)
    expect(frame.postMessage.mock.calls[0]![0]).toMatchObject({ id: 2, ok: false })

    release('done')
    await first

    expect(frame.postMessage.mock.calls[1]![0]).toMatchObject({ id: 1, ok: true, result: 'done' })

    // The refused call spent nothing: nine more still fit (1 + 9 = 10).
    for (let i = 0; i < MAX_ASKS_PER_MINUTE - 1; i += 1) {
      release = () => {}
      ask.mockImplementationOnce(async () => 'ok')
      await send(request({ id: 10 + i }))
      expect(frame.postMessage.mock.calls.at(-1)![0]).toMatchObject({ ok: true })
    }
  })
})

describe('saved data', () => {
  const save = (key: unknown, value: unknown, id = 1) => request({ id, json: JSON.stringify(value), key, op: 'save' })
  const load = (key: unknown, id = 2) => request({ id, key, op: 'load' })

  it('round-trips a value through save then load', async () => {
    const { lastReply, send } = setup()

    await send(save('todo', { items: ['a', 'b'], done: 1 }))
    expect(lastReply()).toMatchObject({ ok: true, result: true })

    await send(load('todo'))
    expect(lastReply()).toMatchObject({ ok: true, result: { done: 1, items: ['a', 'b'] } })
  })

  it('loads null for a key that was never saved', async () => {
    const { lastReply, send } = setup()

    await send(load('nothing'))

    expect(lastReply()).toMatchObject({ ok: true, result: null })
  })

  it('keeps data in the parent storage, keyed by the artifact content', async () => {
    const { send, storage } = setup()

    await send(save('k', 'v'))

    expect([...storage.items.keys()]).toHaveLength(1)
    expect([...storage.items.keys()][0]).toContain('page-a')
  })

  it('isolates one artifact from another', async () => {
    const storage = memoryStorage()
    let key = 'page-a'
    const { lastReply, send } = setup({ contentKey: () => key, storage })

    await send(save('k', 'from a'))

    key = 'page-b'
    await send(load('k'))
    expect(lastReply()).toMatchObject({ ok: true, result: null })

    key = 'page-a'
    await send(load('k'))
    expect(lastReply()).toMatchObject({ ok: true, result: 'from a' })
  })

  it('treats a __proto__ key as plain data, not a prototype write', async () => {
    const { lastReply, send } = setup()

    await send(save('__proto__', { polluted: true }))
    expect(lastReply().ok).toBe(true)
    expect(({} as Record<string, unknown>).polluted).toBeUndefined()

    await send(load('__proto__'))
    expect(lastReply()).toMatchObject({ ok: true, result: { polluted: true } })
  })

  it('refuses a save past 64 KB and leaves the earlier data alone', async () => {
    const { lastReply, send } = setup()

    await send(save('small', 'kept'))
    await send(save('big', 'x'.repeat(MAX_DATA_BYTES)))

    expect(lastReply().ok).toBe(false)
    expect(String(lastReply().error)).toContain('64 KB')

    await send(load('small'))
    expect(lastReply()).toMatchObject({ ok: true, result: 'kept' })
  })

  it('refuses a bad key or an unparseable value', async () => {
    const { lastReply, send } = setup()

    await send(save('', 'v'))
    expect(lastReply().ok).toBe(false)

    await send(save('k'.repeat(129), 'v'))
    expect(lastReply().ok).toBe(false)

    await send(save(42, 'v'))
    expect(lastReply().ok).toBe(false)

    await send(request({ json: '{not json', key: 'k', op: 'save' }))
    expect(lastReply().ok).toBe(false)

    await send(request({ key: 'k', op: 'save' }))
    expect(lastReply().ok).toBe(false)

    await send(load(''))
    expect(lastReply().ok).toBe(false)
  })

  it('survives a damaged stored entry', async () => {
    const { lastReply, send, storage } = setup()

    storage.items.set('harvis-artifact-data:v1:page-a', '{broken')

    await send(load('k'))
    expect(lastReply()).toMatchObject({ ok: true, result: null })

    await send(save('k', 1))
    expect(lastReply().ok).toBe(true)
  })

  it('still saves for the session when browser storage throws', async () => {
    const storage = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      }
    }

    const { lastReply, send } = setup({ storage })

    await send(save('k', 'kept in memory'))
    expect(lastReply().ok).toBe(true)

    await send(load('k'))
    expect(lastReply()).toMatchObject({ ok: true, result: 'kept in memory' })
  })

  it('keeps the newest value when storage fills up after an earlier save', async () => {
    const items = new Map<string, string>()
    let full = false
    const storage = {
      getItem: (key: string) => items.get(key) ?? null,
      setItem: (key: string, value: string) => {
        if (full) {
          throw new DOMException('quota', 'QuotaExceededError')
        }

        items.set(key, value)
      }
    }

    const { lastReply, send } = setup({ storage })

    await send(save('a', 1))
    expect(lastReply().ok).toBe(true)

    full = true
    await send(save('a', 2))
    expect(lastReply().ok).toBe(true)

    await send(load('a'))
    expect(lastReply()).toMatchObject({ ok: true, result: 2 })

    // A later save builds on the newer map, not the stale stored one.
    await send(save('b', 3))
    await send(load('a'))
    expect(lastReply()).toMatchObject({ ok: true, result: 2 })
    await send(load('b'))
    expect(lastReply()).toMatchObject({ ok: true, result: 3 })

    // Once storage has room again, the next save lands there and wins.
    full = false
    await send(save('a', 4))
    await send(load('a'))
    expect(lastReply()).toMatchObject({ ok: true, result: 4 })
    expect(items.get([...items.keys()][0])).toContain('"a":4')
  })

  it('works with no storage at all', async () => {
    const { lastReply, send } = setup({ storage: null })

    await send(save('k', [1, 2]))
    await send(load('k'))

    expect(lastReply()).toMatchObject({ ok: true, result: [1, 2] })
  })
})

describe('artifactDataKey', () => {
  it('is stable for the same page and differs for different pages', () => {
    expect(artifactDataKey('<h1>a</h1>')).toBe(artifactDataKey('<h1>a</h1>'))
    expect(artifactDataKey('<h1>a</h1>')).not.toBe(artifactDataKey('<h1>b</h1>'))
  })
})

describe('injected scripts and the sandbox', () => {
  const scripts = (token = TOKEN) => bridgeStubScript() + bridgeTransportScript(token)

  it('contains no allow-same-origin, and never reaches for the parent app', () => {
    expect(scripts()).not.toContain('allow-same-origin')
    expect(scripts()).not.toMatch(/parent\.(document|location|window)|top\./)
    expect(withArtifactBridge('<html><head></head><body></body></html>', TOKEN)).not.toContain('allow-same-origin')
  })

  it.each([
    '../components/assistant-ui/inline-preview-directive.tsx',
    '../app/chat/right-rail/preview-artifact.tsx'
  ])('keeps the iframe sandbox at allow-scripts only in %s', file => {
    const source = readFileSync(new URL(file, import.meta.url), 'utf8')

    // The JSX attribute lines only; the doc comments may talk about allow-same-origin.
    const attributes = source.split('\n').filter(line => /^\s*sandbox=/.test(line))

    expect(attributes.length).toBeGreaterThan(0)

    for (const line of attributes) {
      expect(line.trim()).toBe('sandbox="allow-scripts"')
    }
  })

  it('puts the stub in <head> ahead of the page scripts and the transport last', () => {
    const doc = '<!doctype html><html><head><title>t</title></head><body><h1>x</h1><script>init()</script></body></html>'
    const out = withArtifactBridge(doc, TOKEN)

    expect(out.indexOf('window.harvis=')).toBeGreaterThan(out.indexOf('<head>'))
    expect(out.indexOf('window.harvis=')).toBeLessThan(out.indexOf('<title>'))
    expect(out.indexOf('init()')).toBeGreaterThan(out.indexOf('window.harvis='))
    expect(out.indexOf('postMessage')).toBeGreaterThan(out.indexOf('init()'))
    expect(out.indexOf('postMessage')).toBeLessThan(out.lastIndexOf('</body>'))
    expect(out.startsWith('<!doctype html>')).toBe(true)
  })

  it('handles documents with no head, no html, or no body close', () => {
    expect(withArtifactBridge('<html><body><p>a</p></body></html>', TOKEN)).toMatch(/<html><script>/)
    expect(withArtifactBridge('<p>fragment</p>', TOKEN).startsWith('<script>')).toBe(true)
    expect(withArtifactBridge('<p>fragment</p>', TOKEN).endsWith('</script>')).toBe(true)
    expect(withArtifactBridge('<!doctype html><p>a</p>', TOKEN).startsWith('<!doctype html><script>')).toBe(true)
  })

  it('does not mistake <header> for <head>', () => {
    const out = withArtifactBridge('<html><body><header>h</header></body></html>', TOKEN)

    expect(out.indexOf('window.harvis=')).toBeLessThan(out.indexOf('<header>'))
    expect(out).toContain('<html><script>')
  })

  it('carries the token only as a JSON string literal', () => {
    expect(bridgeTransportScript('a"b</script>')).not.toContain('a"b</script>')
  })
})

/** Run the two injected scripts against a fake frame wired to a real host. */
function runPage(hostOver: Partial<Parameters<typeof createBridgeHost>[0]> = {}) {
  const listeners: ((event: { data: unknown; source: unknown }) => void)[] = []
  const parent = { postMessage: vi.fn() }
  const win: Record<string, unknown> = {}

  const frameWindow = {
    postMessage: (data: unknown) => listeners.forEach(listener => listener({ data, source: parent }))
  }

  const host = createBridgeHost({
    contentKey: () => 'page-a',
    frame: () => frameWindow,
    storage: memoryStorage(),
    token: TOKEN,
    ...hostOver
  })

  const pending: Promise<boolean>[] = []

  parent.postMessage.mockImplementation((data: unknown) => {
    pending.push(host.handle({ data, source: frameWindow }))
  })

  const body = (script: string) => script.replace(/^<script>/, '').replace(/<\/script>$/, '')

  const run = (script: string) =>
    new Function('window', 'parent', 'addEventListener', body(script))(win, parent, (_: string, fn: never) =>
      listeners.push(fn)
    )

  return { parent, pending, run, win }
}

describe('page-side script, end to end', () => {
  it('askModel resolves with the reply, and a call made before the transport loads is queued', async () => {
    const ask = vi.fn(async (p: string) => `re: ${p}`)
    const { pending, run, win } = runPage({ ask })

    run(bridgeStubScript())

    const harvis = win.harvis as { askModel: (p: string) => Promise<string> }
    const early = harvis.askModel('early')
    const captured = harvis.askModel // a page may keep its own reference

    run(bridgeTransportScript(TOKEN))

    await expect(early).resolves.toBe('re: early')
    await expect(captured('later')).resolves.toBe('re: later')
    expect(pending.length).toBe(2)
  })

  it('saveData then loadData round-trips through the host', async () => {
    const { run, win } = runPage()

    run(bridgeStubScript())
    run(bridgeTransportScript(TOKEN))

    const harvis = win.harvis as {
      loadData: (k: string) => Promise<unknown>
      saveData: (k: string, v: unknown) => Promise<boolean>
    }

    await expect(harvis.saveData('score', { best: 12 })).resolves.toBe(true)
    await expect(harvis.loadData('score')).resolves.toEqual({ best: 12 })
    await expect(harvis.loadData('missing')).resolves.toBeNull()
  })

  it('rejects over-long prompts and bad keys inside the page, before any message is sent', async () => {
    const { parent, run, win } = runPage()

    run(bridgeStubScript())
    run(bridgeTransportScript(TOKEN))

    const harvis = win.harvis as {
      askModel: (p: unknown) => Promise<string>
      saveData: (k: unknown, v: unknown) => Promise<boolean>
    }

    await expect(harvis.askModel('x'.repeat(MAX_ASK_PROMPT + 1))).rejects.toThrow(/limited/)
    await expect(harvis.askModel('')).rejects.toThrow()
    await expect(harvis.saveData('', 1)).rejects.toThrow()
    await expect(harvis.saveData('k', undefined)).rejects.toThrow()
    expect(parent.postMessage).not.toHaveBeenCalled()
  })

  it('surfaces a host refusal as a rejected promise', async () => {
    const { run, win } = runPage({ now: () => 5 })

    run(bridgeStubScript())
    run(bridgeTransportScript(TOKEN))

    const ask = (win.harvis as { askModel: (p: string) => Promise<string> }).askModel

    // With no `ask` override the host would hit fetch; stub it to a fixed reply.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ choices: [{ message: { content: 'fine' } }] }), { status: 200 }))
    )

    for (let i = 0; i < MAX_ASKS_PER_MINUTE; i += 1) {
      await expect(ask(`q${i}`)).resolves.toBe('fine')
    }

    await expect(ask('one too many')).rejects.toThrow(/minute/)
  })

  it('ignores a reply from another window or with another token', async () => {
    const listeners: ((event: { data: unknown; source: unknown }) => void)[] = []
    const parent = { postMessage: vi.fn() }
    const win: Record<string, unknown> = {}
    const strip = (script: string) => script.replace(/^<script>/, '').replace(/<\/script>$/, '')

    new Function('window', 'parent', 'addEventListener', `${strip(bridgeStubScript())};${strip(bridgeTransportScript(TOKEN))}`)(
      win,
      parent,
      (_: string, fn: never) => listeners.push(fn)
    )

    const asked = (win.harvis as { askModel: (p: string) => Promise<string> }).askModel('hi')
    const { id } = parent.postMessage.mock.calls[0]![0] as { id: number }
    const settled = vi.fn()

    void asked.then(settled, settled)

    const reply = (token: string, result: string) => ({ id, ok: true, result, token, type: RESPONSE_MESSAGE_TYPE })

    listeners[0]!({ data: reply(TOKEN, 'wrong window'), source: {} })
    listeners[0]!({ data: reply('other', 'wrong token'), source: parent })
    await Promise.resolve()
    expect(settled).not.toHaveBeenCalled()

    listeners[0]!({ data: reply(TOKEN, 'real'), source: parent })
    await expect(asked).resolves.toBe('real')
  })
})

describe('askHarvis', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    reportUnauthorized.mockReset()
  })

  const reply = (content: unknown, status = 200) =>
    vi.fn(async () => new Response(JSON.stringify({ choices: [{ message: { content } }] }), { status }))

  it('posts one plain, non-streamed, tool-free turn with the session cookie', async () => {
    const fetchMock = reply('a joke')

    vi.stubGlobal('fetch', fetchMock)

    await expect(askHarvis('tell me a joke')).resolves.toBe('a joke')

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    const body = JSON.parse(String(init.body))

    expect(url).toBe(ASK_ENDPOINT)
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(body).toMatchObject({
      harvis_plain: true,
      messages: [{ content: 'tell me a joke', role: 'user' }],
      stream: false
    })
    expect(body.max_tokens).toBeGreaterThan(0)
    expect(body.tools).toBeUndefined()
  })

  it('strips a reasoning block from the answer', async () => {
    vi.stubGlobal('fetch', reply('<think>hmm</think>\n\nBecause it was tired.'))

    await expect(askHarvis('why')).resolves.toBe('Because it was tired.')
  })

  it('asks the session watcher to re-check on a 401, and throws a plain message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"secret"}', { status: 401 })))

    await expect(askHarvis('hi')).rejects.toThrow('Harvis could not answer (401).')
    expect(reportUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('fails plainly on an empty answer and on a network error', async () => {
    vi.stubGlobal('fetch', reply('   '))
    await expect(askHarvis('hi')).rejects.toThrow('empty')

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('network down: 10.0.0.5')
      })
    )

    const error = await askHarvis('hi').catch((e: Error) => e)

    expect((error as Error).message).toBe('Harvis is not answering right now.')
  })
})
