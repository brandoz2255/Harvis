/**
 * OpenClaw chat state store.
 *
 * Manages chat messages, streaming, tool stream sidebar, and focus mode.
 */

import { create } from "zustand"
import type { NormalizedMessage, MessageGroup, ToolCard, ChatAttachment } from "@/lib/openclaw/types"

export type ChatState = {
  // Core state
  messages: NormalizedMessage[]
  chatStream: string | null
  chatStreamStartedAt: number | null
  chatRunId: string | null
  chatThinkingLevel: string | null
  chatSending: boolean
  chatMessage: string
  chatAttachments: ChatAttachment[]

  // Tool stream sidebar
  toolStream: Array<{
    toolCallId: string
    name: string
    args?: unknown
    text?: string
    kind: "call" | "result"
  }>

  // UI state
  focusMode: boolean
  showThinking: boolean
  chatQueue: string[]
  belowFold: boolean

  // Actions
  setMessages: (messages: NormalizedMessage[]) => void
  appendMessage: (msg: NormalizedMessage) => void
  updateStream: (text: string, runId?: string, thinkingLevel?: string) => void
  clearStream: () => void
  setChatSending: (sending: boolean) => void
  setChatMessage: (message: string) => void
  setAttachments: (attachments: ChatAttachment[]) => void
  addToolStreamEntry: (entry: { toolCallId: string; name: string; args?: unknown; text?: string; kind: "call" | "result" }) => void
  clearToolStream: () => void
  setFocusMode: (focus: boolean) => void
  setShowThinking: (show: boolean) => void
  addToQueue: (message: string) => void
  processQueue: () => void
  setBelowFold: (below: boolean) => void
  toggleFocusMode: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  chatStream: null,
  chatStreamStartedAt: null,
  chatRunId: null,
  chatThinkingLevel: null,
  chatSending: false,
  chatMessage: "",
  chatAttachments: [],
  toolStream: [],
  focusMode: false,
  showThinking: false,
  chatQueue: [],
  belowFold: false,

  setMessages: (messages) => set({ messages }),

  appendMessage: (msg) =>
    set((state) => ({
      messages: [...state.messages, msg],
    })),

  updateStream: (text, runId, thinkingLevel) =>
    set({
      chatStream: text,
      chatStreamStartedAt: get().chatStreamStartedAt ?? Date.now(),
      chatRunId: runId ?? get().chatRunId,
      chatThinkingLevel: thinkingLevel ?? get().chatThinkingLevel,
    }),

  clearStream: () =>
    set({
      chatStream: null,
      chatStreamStartedAt: null,
      chatThinkingLevel: null,
    }),

  setChatSending: (chatSending) => set({ chatSending }),

  setChatMessage: (chatMessage) => set({ chatMessage }),

  setAttachments: (chatAttachments) => set({ chatAttachments }),

  addToolStreamEntry: (entry) =>
    set((state) => {
      const existing = state.toolStream.findIndex((t) => t.toolCallId === entry.toolCallId)
      if (existing >= 0) {
        const updated = [...state.toolStream]
        updated[existing] = entry
        return { toolStream: updated }
      }
      // Limit to 50 entries
      const newStream = [...state.toolStream, entry]
      return newStream.length > 50 ? { toolStream: newStream.slice(-50) } : { toolStream: newStream }
    }),

  clearToolStream: () => set({ toolStream: [] }),

  setFocusMode: (focusMode) => set({ focusMode }),

  setShowThinking: (showThinking) => set({ showThinking }),

  addToQueue: (message) =>
    set((state) => ({ chatQueue: [...state.chatQueue, message] })),

  processQueue: async () => {
    const { chatQueue, setChatSending } = get()
    if (chatQueue.length === 0) return

    setChatSending(true)
    // Queue processing is handled by the useOpenClawChat hook
    set({ chatQueue: [] })
    setChatSending(false)
  },

  setBelowFold: (belowFold) => set({ belowFold }),

  toggleFocusMode: () => set((state) => ({ focusMode: !state.focusMode })),
}))
