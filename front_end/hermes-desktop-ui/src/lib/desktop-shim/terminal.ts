// The browser build's PTY: one WebSocket per terminal tab to the chat's sandbox
// container (python_back_end/plugins/hermes_ui/rest_sandbox.py). Same surface
// as Electron's `window.hermesDesktop.terminal`, so the xterm panes under
// src/app/right-sidebar/terminal/ run unmodified.
//
// Frames are small JSON text messages: we send {t:'i',d} for keys and
// {t:'r',c,r} for resize; the server sends {t:'ready'}, {t:'o',d} output,
// {t:'x',code} on exit and {t:'e',message} when the sandbox can't start.

import type { HermesTerminalExit, HermesTerminalSession } from '@/global'

type DataListener = (payload: string) => void
type ExitListener = (payload: HermesTerminalExit) => void

interface Term {
  ws: WebSocket
  cwd: string
  data: Set<DataListener>
  exit: Set<ExitListener>
  // Output that arrives before the pane subscribes (the first prompt usually does).
  pending: string[]
  exited: HermesTerminalExit | null
}

const API_BASE: string = (import.meta as any).env?.VITE_HERMES_API_BASE ?? ''
const START_TIMEOUT_MS = 60_000 // a cold sandbox may need to start its container first
const terms = new Map<string, Term>()
let counter = 0

function terminalUrl(options: { cols?: number; cwd?: string; rows?: number }): string {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const q = new URLSearchParams({ cwd: options.cwd ?? '' })

  if (options.cols) q.set('cols', String(options.cols))
  if (options.rows) q.set('rows', String(options.rows))

  return `${scheme}//${location.host}${API_BASE}/api/terminal/ws?${q}`
}

function finish(term: Term, exit: HermesTerminalExit) {
  if (term.exited) return
  term.exited = exit
  for (const listener of term.exit) listener(exit)
}

function send(term: Term, frame: object): boolean {
  if (term.ws.readyState !== WebSocket.OPEN) return false
  term.ws.send(JSON.stringify(frame))
  return true
}

async function start(options: { cols?: number; cwd?: string; rows?: number } = {}): Promise<HermesTerminalSession> {
  const id = `sandbox-${Date.now()}-${++counter}`
  const ws = new WebSocket(terminalUrl(options))
  const term: Term = { ws, cwd: options.cwd ?? '', data: new Set(), exit: new Set(), pending: [], exited: null }

  await new Promise<void>((resolve, reject) => {
    let ready = false
    const timer = setTimeout(() => {
      reject(new Error('The sandbox took too long to start.'))
      ws.close()
    }, START_TIMEOUT_MS)

    ws.onmessage = event => {
      let frame: { t?: string; d?: string; code?: null | number; message?: string }

      try {
        frame = JSON.parse(String(event.data))
      } catch {
        return
      }

      if (frame.t === 'ready') {
        ready = true
        clearTimeout(timer)
        resolve()
      } else if (frame.t === 'o' && typeof frame.d === 'string') {
        if (term.data.size) {
          for (const listener of term.data) listener(frame.d)
        } else {
          term.pending.push(frame.d)
        }
      } else if (frame.t === 'x') {
        finish(term, { code: frame.code ?? null, signal: null })
      } else if (frame.t === 'e') {
        clearTimeout(timer)
        reject(new Error(frame.message || 'The sandbox could not start.'))
      }
    }

    ws.onclose = () => {
      clearTimeout(timer)

      if (!ready) {
        reject(new Error('Could not connect to the sandbox terminal.'))
      }

      finish(term, { code: null, signal: 'SIGHUP' })
    }
  })

  terms.set(id, term)

  return { id, cwd: term.cwd, shell: 'bash' }
}

export const sandboxTerminal = {
  start,
  write: async (id: string, data: string) => {
    const term = terms.get(id)

    return term ? send(term, { t: 'i', d: data }) : false
  },
  resize: async (id: string, size: { cols: number; rows: number }) => {
    const term = terms.get(id)

    return term ? send(term, { t: 'r', c: size.cols, r: size.rows }) : false
  },
  dispose: async (id: string) => {
    const term = terms.get(id)

    if (!term) return false
    terms.delete(id)
    term.ws.close()

    return true
  },
  // The shell's live cwd isn't tracked; reopening starts at the sandbox root.
  cwd: async () => null,
  onData: (id: string, callback: DataListener) => {
    const term = terms.get(id)

    if (!term) return () => undefined
    term.data.add(callback)

    for (const chunk of term.pending.splice(0)) callback(chunk)

    return () => term.data.delete(callback)
  },
  onExit: (id: string, callback: ExitListener) => {
    const term = terms.get(id)

    if (!term) return () => undefined

    if (term.exited) {
      callback(term.exited)

      return () => undefined
    }

    term.exit.add(callback)

    return () => term.exit.delete(callback)
  }
}
