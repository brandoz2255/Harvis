import {
  Button,
  Codicon,
  ConfirmDialog,
  host,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Switch,
  useQuery,
  useQueryClient,
  useValue
} from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'

import { openPreview } from '@/store/preview'

import { harvisApi } from './api'
import { formatBytes } from './format'

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
  apps: SandboxApp[]
}

const BASE = '/hermes-api/api/sandbox'
export const sandboxKey = (sessionId: string) => ['harvis', 'sandbox', sessionId] as const

export const fetchSandbox = (sessionId: string) =>
  harvisApi<SandboxInfo>(`${BASE}/info?session=${encodeURIComponent(sessionId)}`)

/** Open an app the sandbox is serving in the right panel's browser. */
export function openApp(app: SandboxApp) {
  const url = new URL(app.url, window.location.origin).toString()

  openPreview({ kind: 'url', label: `Sandbox :${app.port}`, source: url, url })
}

/**
 * The chat's sandbox (python_back_end/plugins/hermes_ui/sandbox.py): the folder
 * and container the right sidebar's Files and Terminal show, where Harvis
 * installs things you ask for. This button shows how big it is, the apps it's
 * serving (Open puts one in the right panel), the GPU switch, and Delete. A new
 * app coming up pops a toast, so you don't have to go looking.
 */
export function SandboxButton() {
  const sessionId = useValue(host.state.focusedStoredSessionId)
  const busy = useValue(host.state.busy)
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')
  const seenPorts = useRef<{ ports: Set<number>; sessionId: string } | null>(null)

  const info = useQuery({
    enabled: Boolean(sessionId),
    queryFn: () => fetchSandbox(sessionId as string),
    queryKey: sandboxKey(sessionId ?? ''),
    refetchInterval: open ? 5_000 : busy ? 10_000 : 30_000,
    retry: false
  })

  const data = info.data
  const apps = data?.apps ?? []

  // Toast the first time a reachable app shows up (not the ones already running when
  // the chat was opened).
  useEffect(() => {
    if (!sessionId || !data) {
      return
    }

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
  }, [apps, data, sessionId])

  if (!sessionId || !data?.cwd) {
    return null
  }

  const refresh = () => void queryClient.invalidateQueries({ queryKey: sandboxKey(sessionId) })

  const setGpu = async (on: boolean) => {
    setError('')

    try {
      await harvisApi(`${BASE}/gpu`, { method: 'POST', body: JSON.stringify({ session: sessionId, on }) })
      refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const running = apps.some(a => a.public)

  return (
    <>
      <Popover onOpenChange={setOpen} open={open}>
        <PopoverTrigger asChild>
          <button
            aria-label="This chat's sandbox"
            className="relative inline-flex size-7 items-center justify-center rounded-full text-(--ui-text-secondary) transition-colors hover:bg-accent/60"
            title="This chat's sandbox"
            type="button"
          >
            <Codicon name="vm" size="0.85rem" />
            {(running || data.over_warn) && (
              <span
                className={`absolute top-1 right-1 size-1.5 rounded-full ${data.over_warn ? 'bg-amber-500' : 'bg-emerald-500'}`}
              />
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 space-y-3 p-3" side="top">
          <div>
            <p className="text-sm font-medium">This chat's sandbox</p>
            <p className="text-xs text-(--ui-text-tertiary)">
              Where Harvis installs and runs things for this chat. Its files and a terminal are in the right sidebar.
            </p>
          </div>

          <div className="flex items-center justify-between text-xs">
            <span className="text-(--ui-text-secondary)">Disk used</span>
            <span className={data.over_warn ? 'font-medium text-amber-600 dark:text-amber-300' : ''}>
              {formatBytes(data.size_bytes)}
            </span>
          </div>
          {data.over_warn && (
            <p className="text-xs text-amber-600 dark:text-amber-300">
              Over {formatBytes(data.warn_bytes)}. Delete it when you're done to free the space.
            </p>
          )}

          <div className="space-y-1">
            <p className="text-xs text-(--ui-text-secondary)">Apps</p>
            {apps.length === 0 ? (
              <p className="text-xs text-(--ui-text-tertiary)">
                {data.running ? 'Nothing is serving yet.' : 'Not running. Ask Harvis to install or start something.'}
              </p>
            ) : (
              apps.map(app => (
                <div className="flex items-center gap-2 text-xs" key={app.port}>
                  <Codicon name="globe" size="0.8rem" />
                  <span className="flex-1">Port {app.port}</span>
                  {app.public ? (
                    <Button onClick={() => openApp(app)} size="sm" variant="ghost">
                      Open
                    </Button>
                  ) : (
                    <span className="text-(--ui-text-tertiary)" title="Ask Harvis to start it on 0.0.0.0">
                      localhost only
                    </span>
                  )}
                </div>
              ))
            )}
          </div>

          <label className="flex items-center justify-between gap-2 text-xs">
            <span>
              <span className="block">Use the GPU</span>
              <span className="block text-(--ui-text-tertiary)">
                {data.gpu_available ? 'Restarts the sandbox. Can slow down chat and voice.' : 'No GPU is available here.'}
              </span>
            </span>
            <Switch
              checked={data.gpu}
              disabled={!data.gpu_available && !data.gpu}
              onCheckedChange={on => void setGpu(on)}
            />
          </label>

          {error && <p className="text-xs text-destructive">{error}</p>}

          <Button className="w-full" onClick={() => setConfirming(true)} size="sm" variant="ghost">
            <Codicon name="trash" size="0.8rem" /> Delete sandbox
          </Button>
        </PopoverContent>
      </Popover>
      <ConfirmDialog
        confirmLabel="Delete"
        description={`Stops its apps and deletes everything in it (${formatBytes(data.size_bytes)}). The chat itself stays.`}
        destructive
        onClose={() => setConfirming(false)}
        onConfirm={async () => {
          await harvisApi(`${BASE}?session=${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
          refresh()
        }}
        open={confirming}
        title="Delete this chat's sandbox?"
      />
    </>
  )
}
