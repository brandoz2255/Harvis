// The members of `window.hermesDesktop` that have a real browser equivalent.
//
// Everything else lives in `./stubs`. Splitting them keeps the "this actually
// works" list short enough to audit at a glance — when a surface misbehaves in
// the browser build, the question is always "is it here, or is it a stub?".

export interface HermesApiRequest {
  path: string
  method?: string
  body?: unknown
  upload?: { filename: string; contentType?: string; bytes: ArrayBuffer }
  timeoutMs?: number
}

// Hermes' own call sites already spell their paths as `/api/config`,
// `/api/cron/jobs`, … (grep `path: '/` under src/api/). So the base is EMPTY and
// the path is used verbatim — prefixing '/api' here would produce `/api/api/…`.
// The knob exists so a later phase can swing every call onto a `/hermes-api/`
// compat facade without touching the vendored tree.
const API_BASE: string = (import.meta as any).env?.VITE_HERMES_API_BASE ?? ''

const DEFAULT_TIMEOUT_MS = 60_000

export async function api<T>(request: HermesApiRequest): Promise<T> {
  const { path, method, body, upload, timeoutMs } = request
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs ?? DEFAULT_TIMEOUT_MS)

  const init: RequestInit = {
    method: method ?? (body !== undefined || upload ? 'POST' : 'GET'),
    // Harvis authenticates with a session cookie, not the Electron token, so
    // every call has to carry credentials or the backend answers 401.
    credentials: 'include',
    signal: controller.signal,
  }

  if (upload) {
    const form = new FormData()
    form.append(
      'file',
      new Blob([upload.bytes], { type: upload.contentType || 'application/octet-stream' }),
      upload.filename,
    )
    init.body = form // no Content-Type: the browser sets the multipart boundary
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }

  try {
    const res = await fetch(`${API_BASE}${path}`, init)
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail.slice(0, 500)}` : ''}`)
    }
    if (res.status === 204) return undefined as T
    const text = await res.text()
    if (!text) return undefined as T
    try {
      return JSON.parse(text) as T
    } catch {
      // Not every Harvis route answers JSON; hand back the raw body rather than
      // turning a successful call into a parse error.
      return text as unknown as T
    }
  } finally {
    clearTimeout(timer)
  }
}

export function gatewayWsUrl(): string {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${location.host}${API_BASE}/ws`
}

export async function openExternal(url: string): Promise<void> {
  window.open(url, '_blank', 'noopener,noreferrer')
}

export async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export async function readClipboard(): Promise<string> {
  try {
    return await navigator.clipboard.readText()
  } catch {
    // Firefox and any denied permission land here. Empty string beats throwing:
    // a paste that yields nothing is recoverable, an exception unmounts a tree.
    return ''
  }
}

export async function notify(payload: { title?: string; body?: string }): Promise<boolean> {
  try {
    if (!('Notification' in window)) return false
    const permission =
      Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission
    if (permission !== 'granted') return false
    new Notification(payload?.title ?? 'Harvis', { body: payload?.body })
    return true
  } catch {
    return false
  }
}

export function localStore(key: string) {
  return {
    read<T>(fallback: T): T {
      try {
        const raw = localStorage.getItem(key)
        return raw ? (JSON.parse(raw) as T) : fallback
      } catch {
        return fallback
      }
    },
    write<T>(value: T): void {
      try {
        localStorage.setItem(key, JSON.stringify(value))
      } catch {
        /* private mode / quota: a lost preference is not worth an exception */
      }
    },
  }
}
