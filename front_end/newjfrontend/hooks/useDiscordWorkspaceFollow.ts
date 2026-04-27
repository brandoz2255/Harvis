'use client'

import { useEffect, useRef } from 'react'
import { useOpenClawStore } from '@/stores/openclawStore'

const POLL_MS = 3000

/**
 * Polls `/api/workspace/active` while the layout is mounted. When Discord starts a
 * workspace, opens the Harvis workspace panel and attaches the SSE stream once
 * per run id (manual close does not immediately re-auto-open the same run).
 */
export function useDiscordWorkspaceFollow() {
  const autoOpenedRunIdsRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    let cancelled = false

    const tick = async () => {
      try {
        const token = localStorage.getItem('token') || ''
        if (!token) return

        const res = await fetch('/api/workspace/active', {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.status === 404) {
          // Backend returned 404 - clear Discord hint to prevent stale UI
          useOpenClawStore.getState().setDiscordExternalWorkspace(null)
          return
        }
        if (!res.ok || cancelled) return

        const data = await res.json()
        const active = data.active
        const st = useOpenClawStore.getState()

        if (!active) {
          st.setDiscordExternalWorkspace(null)
          return
        }

        if (active.source === 'discord') {
          st.setDiscordExternalWorkspace({
            workspace_id: active.id,
            task_brief: active.task_brief || '',
          })
          const following = st.isWorkspaceActive && st.workspaceId === active.id
          if (
            !following &&
            !autoOpenedRunIdsRef.current.has(active.id)
          ) {
            autoOpenedRunIdsRef.current.add(active.id)
            void st.attachToWorkspaceStream(active.id)
          }
        } else {
          st.setDiscordExternalWorkspace(null)
        }
      } catch {
        // ignore
      }
    }

    void tick()
    const id = window.setInterval(() => void tick(), POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])
}
