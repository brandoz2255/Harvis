/**
 * Hook for OpenClaw chat operations.
 *
 * Provides send, abort, history loading, and session switching.
 */

import { useCallback, useState } from "react"
import { useConnectionStore } from "@/stores/openclawConnectionStore"
import { useChatStore } from "@/stores/openclawChatStore"
import { useSessionsStore } from "@/stores/openclawSessionsStore"

export function useOpenClawChat() {
  const client = useConnectionStore((s) => s.client)
  const chatMessage = useChatStore((s) => s.chatMessage)
  const setChatMessage = useChatStore((s) => s.setChatMessage)
  const setChatSending = useChatStore((s) => s.setChatSending)
  const chatStream = useChatStore((s) => s.chatStream)
  const chatRunId = useChatStore((s) => s.chatRunId)
  const messages = useChatStore((s) => s.messages)
  const appendMessage = useChatStore((s) => s.appendMessage)
  const clearStream = useChatStore((s) => s.clearStream)
  const clearToolStream = useChatStore((s) => s.clearToolStream)

  const activeSessionKey = useSessionsStore((s) => s.activeSessionKey)
  const setActiveSession = useSessionsStore((s) => s.activeSessionKey)

  const [aborting, setAborting] = useState(false)

  /** Send a chat message */
  const send = useCallback(async (text?: string) => {
    if (!client || !client.connected) return

    const message = text ?? chatMessage
    if (!message.trim()) return

    setChatMessage("")
    setChatSending(true)
    clearStream()
    clearToolStream()

    try {
      await client.sendChat(message)
    } catch (e) {
      console.error("[OpenClawChat] Failed to send:", e)
      setChatSending(false)
    }
  }, [client, chatMessage, setChatMessage, setChatSending, clearStream, clearToolStream])

  /** Abort current run */
  const abort = useCallback(async () => {
    if (!client || !client.connected || !chatRunId) return

    setAborting(true)
    try {
      await client.abortChat(chatRunId)
    } catch (e) {
      console.error("[OpenClawChat] Failed to abort:", e)
    } finally {
      setAborting(false)
    }
  }, [client, chatRunId])

  /** Load chat history for the current session */
  const loadHistory = useCallback(async () => {
    if (!client || !client.connected) return

    try {
      const result = await client.loadChatHistory()
      if (result.type === "res" && result.ok) {
        const messages = (result.payload as any)?.messages ?? []
        // Messages are already normalized by the backend relay
        // Just append them to the store
        for (const msg of messages) {
          appendMessage(msg)
        }
      }
    } catch (e) {
      console.error("[OpenClawChat] Failed to load history:", e)
    }
  }, [client, appendMessage])

  /** Switch to a different session */
  const switchSession = useCallback(async (sessionKey: string) => {
    if (!client || !client.connected) return

    client.switchSession(sessionKey)
    setActiveSession(sessionKey)

    // Clear chat and load history for new session
    useChatStore.getState().setMessages([])
    clearStream()
    clearToolStream()

    await loadHistory()
  }, [client, setActiveSession, loadHistory, clearStream, clearToolStream])

  return {
    send,
    abort,
    loadHistory,
    switchSession,
    chatMessage,
    setChatMessage,
    chatStream,
    chatRunId,
    messages,
    aborting,
  }
}
