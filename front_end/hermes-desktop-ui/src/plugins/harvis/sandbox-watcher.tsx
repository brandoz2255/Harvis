import { host, useQuery, useValue } from '@hermes/plugin-sdk'
import { useEffect, useRef } from 'react'

import { setFileBrowserOpen } from '@/store/layout'
import { openPreview } from '@/store/preview'

import { harvisApi } from './api'

export interface SandboxApp {
  port: number
  public: boolean
  url: string
}

export interface SandboxInfo {
  cwd: null | string
  size_bytes: number
  warn_bytes: number
  over_warn: boolean
  gpu: boolean
  gpu_available: boolean
  running: boolean
  /** Its container is being started in the background (it starts when the chat opens). */
  starting?: boolean
  apps: SandboxApp[]
}

const BASE = '/hermes-api/api/sandbox'
// The Files pane opens by itself the first time a chat's sandbox shows up; after
// that it stays however the user leaves it.
const FILES_SHOWN_KEY = 'harvis.sandbox.filesPaneShown'
export const sandboxKey = (sessionId: string) => ['harvis', 'sandbox', sessionId] as const

export const fetchSandbox = (sessionId: string) =>
  harvisApi<SandboxInfo>(`${BASE}/info?session=${encodeURIComponent(sessionId)}`)

/** Open an app the sandbox is serving in the right panel's browser. */
export function openApp(app: SandboxApp) {
  const url = new URL(app.url, window.location.origin).toString()

  openPreview({ kind: 'url', label: `Sandbox :${app.port}`, source: url, url })
}

/**
 * The chat's sandbox (python_back_end/plugins/hermes_ui/sandbox.py) is automatic:
 * asking for its info starts it and mirrors the skills and core files (SOUL.md,
 * USER.md, MEMORY.md, AGENTS.md) into it. This renders nothing. It keeps that
 * info fresh, opens the Files pane the first time a sandbox shows up, and pops
 * an "App ready" toast with an Open button when a new app starts serving.
 */
export function SandboxWatcher() {
  const sessionId = useValue(host.state.focusedStoredSessionId)
  const busy = useValue(host.state.busy)
  const seenPorts = useRef<{ ports: Set<number>; sessionId: string } | null>(null)

  const info = useQuery({
    enabled: Boolean(sessionId),
    queryFn: () => fetchSandbox(sessionId as string),
    queryKey: sandboxKey(sessionId ?? ''),
    refetchInterval: query => (query.state.data?.starting ? 3_000 : busy ? 5_000 : 30_000),
    retry: false
  })

  const data = info.data
  const hasSandbox = Boolean(data?.cwd)

  useEffect(() => {
    if (!hasSandbox) {
      return
    }

    try {
      if (window.localStorage.getItem(FILES_SHOWN_KEY)) {
        return
      }

      window.localStorage.setItem(FILES_SHOWN_KEY, '1')
    } catch {
      return
    }

    setFileBrowserOpen(true)
  }, [hasSandbox])

  // Toast the first time a reachable app shows up (not the ones already running when
  // the chat was opened).
  useEffect(() => {
    if (!sessionId || !data) {
      return
    }

    const apps = data.apps ?? []
    const ports = new Set(apps.filter(a => a.public).map(a => a.port))
    const prev = seenPorts.current

    if (prev && prev.sessionId === sessionId) {
      for (const app of apps) {
        if (app.public && !prev.ports.has(app.port)) {
          host.notify({
            id: `harvis-sandbox-app-${sessionId}-${app.port}`,
            kind: 'info',
            icon: 'globe',
            title: 'App ready in the sandbox',
            message: `Something is serving on port ${app.port}.`,
            durationMs: 0,
            action: { label: 'Open', onClick: () => openApp(app) }
          })
        }
      }
    }

    seenPorts.current = { ports, sessionId }
  }, [data, sessionId])

  return null
}
