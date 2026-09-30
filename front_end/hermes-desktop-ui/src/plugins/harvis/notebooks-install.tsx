/**
 * Notebooks' one install step: an embedding model on the model server
 * (python_back_end/notebooks/embedder_status.py). Until it is there the sidebar
 * row is dimmed and the Notebooks page opens with this panel, which offers the
 * download with its size. Same backend routes the setup wizard's Verify step uses.
 */

import { Button, Codicon } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { setNavDimmed } from '@/store/nav-status'

import { harvisApi } from './api'

export interface EmbedderStatus {
  state: 'not_installed' | 'ready' | 'unreachable' | 'unsupported'
  model: null | string
  install_tag: string
  download_mb: number
  reason: string
}

const NAV_PATH = '/notebooks'

export const embedderKey = ['harvis', 'notebooks-embedder'] as const

export async function fetchEmbedderStatus(): Promise<EmbedderStatus> {
  const st = await harvisApi<EmbedderStatus>('/api/capabilities/notebooks-embedder')

  setNavDimmed(NAV_PATH, st.state === 'ready' ? null : `not installed (${st.download_mb} MB download)`)

  return st
}

/** Dim the sidebar row from app start, not only once the page is opened. */
export function watchNotebooksReady(): () => void {
  fetchEmbedderStatus().catch(() => {
    // Signed out or backend down: leave the row as it is.
  })

  // Plugin switched off: its row goes, so its dimming goes with it.
  return () => setNavDimmed(NAV_PATH, null)
}

async function installEmbedder(onStatus: (line: string) => void): Promise<void> {
  const res = await fetch('/api/capabilities/notebooks-embedder/install', { credentials: 'include', method: 'POST' })

  if (!res.ok || !res.body) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string }

    throw new Error(body.detail || `${res.status} ${res.statusText}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()

    if (done) {
      return
    }

    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const event of events) {
      const line = event.split('\n').find(l => l.startsWith('data:'))

      if (!line) {
        continue
      }

      let ev: { completed?: number; error?: string; status?: string; total?: number }

      try {
        ev = JSON.parse(line.slice(5).trim())
      } catch {
        continue
      }

      if (ev.error) {
        throw new Error(ev.error)
      }

      if (ev.status) {
        onStatus(ev.total ? `${ev.status} ${Math.round((100 * (ev.completed ?? 0)) / ev.total)}%` : ev.status)
      }
    }
  }
}

export function NotebooksInstallPanel({ onInstalled, status }: { onInstalled: () => void; status: EmbedderStatus }) {
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')

  const install = async () => {
    setBusy(true)
    setError('')

    try {
      await installEmbedder(setProgress)
      onInstalled()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const pullable = status.state === 'not_installed'

  return (
    <div className="harvis-glitch-in flex flex-col gap-2 rounded-xl border border-(--ui-stroke-tertiary) bg-(--ui-control-hover-background) px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-medium text-foreground">
        <Codicon name="cloud-download" size="0.95rem" />
        {pullable ? 'Install Notebooks' : 'Notebooks can’t be installed from here'}
      </div>
      <p className="text-xs text-(--ui-text-secondary)">
        {pullable
          ? `Notebooks reads your sources with an embedding model (${status.install_tag}). It is a ${status.download_mb} MB download onto your model server, done once. Until then, adding sources is slow and search is poor.`
          : status.reason}
      </p>
      {pullable && (
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={busy} onClick={() => void install()} size="sm">
            {busy ? 'Installing…' : `Install (${status.download_mb} MB)`}
          </Button>
          {busy && progress && <span className="text-xs tabular-nums text-(--ui-text-tertiary)">{progress}</span>}
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
