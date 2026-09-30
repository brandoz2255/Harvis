import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { sandboxTerminal } from './terminal'

class FakeSocket {
  static OPEN = 1
  static last: FakeSocket
  readyState = 1
  sent: string[] = []
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  constructor(public url: string) {
    FakeSocket.last = this
  }
  send(data: string) {
    this.sent.push(data)
  }
  close() {
    this.readyState = 3
    this.onclose?.()
  }
  emit(frame: object) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }
}

beforeEach(() => vi.stubGlobal('WebSocket', FakeSocket))
afterEach(() => vi.unstubAllGlobals())

async function open(cwd = '/sandbox/s1/workspace') {
  const started = sandboxTerminal.start({ cols: 100, cwd, rows: 30 })
  FakeSocket.last.emit({ t: 'ready' })

  return { session: await started, socket: FakeSocket.last }
}

describe('sandboxTerminal', () => {
  it('connects to the chat sandbox with its cwd and size', async () => {
    const { session, socket } = await open()
    const url = new URL(socket.url)

    expect(url.pathname).toMatch(/\/api\/terminal\/ws$/)
    expect(url.searchParams.get('cwd')).toBe('/sandbox/s1/workspace')
    expect(url.searchParams.get('cols')).toBe('100')
    expect(session.cwd).toBe('/sandbox/s1/workspace')
  })

  it('replays output that arrived before the pane subscribed, then streams', async () => {
    const { session, socket } = await open()
    socket.emit({ t: 'o', d: 'user@sandbox$ ' })

    const seen: string[] = []
    sandboxTerminal.onData(session.id, d => seen.push(d))
    socket.emit({ t: 'o', d: 'ls\r\n' })
    expect(seen).toEqual(['user@sandbox$ ', 'ls\r\n'])
  })

  it('sends keys and resizes as frames, and reports exit', async () => {
    const { session, socket } = await open()
    await sandboxTerminal.write(session.id, 'ls\n')
    await sandboxTerminal.resize(session.id, { cols: 120, rows: 40 })
    expect(socket.sent.map(s => JSON.parse(s))).toEqual([
      { t: 'i', d: 'ls\n' },
      { t: 'r', c: 120, r: 40 }
    ])

    const exits: unknown[] = []
    sandboxTerminal.onExit(session.id, e => exits.push(e))
    socket.emit({ t: 'x', code: 0 })
    expect(exits).toEqual([{ code: 0, signal: null }])
  })

  it('rejects with the server message when the sandbox cannot start', async () => {
    const started = sandboxTerminal.start({ cwd: '/sandbox/s1/workspace' })
    FakeSocket.last.emit({ t: 'e', message: "Docker isn't reachable" })
    await expect(started).rejects.toThrow("Docker isn't reachable")
  })
})
