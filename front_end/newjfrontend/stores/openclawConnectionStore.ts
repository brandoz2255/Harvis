/**
 * OpenClaw connection state store.
 *
 * Manages WebSocket connection lifecycle and status.
 */

import { create } from "zustand"
import { OpenClawClient } from "@/lib/openclaw/client"

export type ConnectionState = {
  client: OpenClawClient | null
  connected: boolean
  connecting: boolean
  lastError: string | null
  hello: unknown
}

type ConnectionStore = ConnectionState & {
  /** Initialize the client and connect */
  connect: () => void
  /** Disconnect from gateway */
  disconnect: () => void
  /** Update connection status */
  setConnected: (connected: boolean) => void
  /** Set error message */
  setError: (error: string | null) => void
  /** Set hello frame payload */
  setHello: (hello: unknown) => void
}

export const useConnectionStore = create<ConnectionStore>((set, get) => ({
  client: null,
  connected: false,
  connecting: false,
  lastError: null,
  hello: null,

   connect: () => {
    const state = get()
    if (state.connected || state.connecting) return
    if (state.client && state.client.connected) return

    // Disconnect old client if exists
    if (state.client) {
      state.client.disconnect()
    }

    set({ connecting: true, lastError: null })

    const client = new OpenClawClient()

    // Set up event listeners BEFORE calling connect()
    client.on("connected", () => {
      set({ connected: true, connecting: false, client })
    })

    client.on("disconnected", () => {
      set({ connected: false, connecting: false })
    })

    client.on("*", (frame) => {
      if (frame.type === "event" && frame.event === "connected") {
        set({ hello: frame.payload })
      }
      if (frame.type === "event" && frame.event === "connecting" && (frame.payload as any)?.refreshingToken) {
        set({ connecting: true, lastError: "Refreshing token..." })
      }
      if (frame.type === "event" && frame.event === "disconnected" && (frame.payload as any)?.reason === "Token expired") {
        set({ connecting: true, lastError: "Token expired, refreshing..." })
      }
    })

    // Now connect - events will be captured
    client.connect()

    set({ client })
  },

  disconnect: () => {
    const { client } = get()
    client?.disconnect()
    set({ connected: false, connecting: false, client: null })
  },

  setConnected: (connected: boolean) => set({ connected }),
  setError: (lastError: string | null) => set({ lastError }),
  setHello: (hello: unknown) => set({ hello }),
}))
