/**
 * OpenClaw sessions state store.
 *
 * Manages session list, active session selection, and session CRUD operations.
 */

import { create } from "zustand"
import type { GatewaySessionRow, SessionsListResult } from "@/lib/openclaw/types"

export type SessionsState = {
  sessions: GatewaySessionRow[]
  activeSessionKey: string | null
  loading: boolean
  error: string | null

  // Actions
  setSessions: (sessions: SessionsListResult) => void
  setActiveSession: (key: string) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  updateSession: (key: string, updates: Partial<GatewaySessionRow>) => void
  removeSession: (key: string) => void
  clearSessions: () => void
}

export const useSessionsStore = create<SessionsState>((set, get) => ({
  sessions: [],
  activeSessionKey: null,
  loading: false,
  error: null,

  setSessions: (result: SessionsListResult) => {
    set({
      sessions: result.sessions,
      error: null,
    })

    // Auto-select the most recent session if none is active
    if (!get().activeSessionKey && result.sessions.length > 0) {
      const sorted = [...result.sessions].sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))
      if (sorted[0]?.key) {
        set({ activeSessionKey: sorted[0].key })
      }
    }
  },

  setActiveSession: (key) => set({ activeSessionKey: key }),

  setLoading: (loading) => set({ loading }),

  setError: (error) => set({ error }),

  updateSession: (key, updates) =>
    set((state) => ({
      sessions: state.sessions.map((s) => (s.key === key ? { ...s, ...updates } : s)),
    })),

  removeSession: (key) =>
    set((state) => ({
      sessions: state.sessions.filter((s) => s.key !== key),
      activeSessionKey: state.activeSessionKey === key ? null : state.activeSessionKey,
    })),

  clearSessions: () => set({ sessions: [], activeSessionKey: null }),
}))
