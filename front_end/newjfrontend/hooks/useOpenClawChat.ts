/**
 * Hook for OpenClaw chat operations.
 *
 * Provides send, abort, history loading, and session switching.
 */

import { useCallback, useEffect, useState } from "react"
import { useConnectionStore } from "@/stores/openclawConnectionStore"
import { useChatStore } from "@/stores/openclawChatStore"
import { useSessionsStore } from "@/stores/openclawSessionsStore"
import type { NormalizedMessage, ChatAttachment } from "@/lib/openclaw/types"

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
  const updateStream = useChatStore((s) => s.updateStream)
  const setMessages = useChatStore((s) => s.setMessages)
  const setThinking = useChatStore((s) => s.setThinking)

  const activeSessionKey = useSessionsStore((s) => s.activeSessionKey)
  const setActiveSession = useSessionsStore((s) => s.setActiveSession)

  const [aborting, setAborting] = useState(false)
  const [currentChatUnsubscribe, setCurrentChatUnsubscribe] = useState<(() => void) | null>(null)

  // Clean up chat event listener on unmount
  useEffect(() => {
    return () => {
      if (currentChatUnsubscribe) {
        currentChatUnsubscribe()
      }
    }
  }, [currentChatUnsubscribe])

  /** Send a chat message */
  const send = useCallback(async (text?: string, attachments?: Array<{ name: string; type: string; data: string }>) => {
    if (!client || !client.connected) return

    const message = text ?? chatMessage
    if (!message.trim()) return

    setChatMessage("")
    setChatSending(true)
    setThinking(true)
    clearStream()
    clearToolStream()

    // Add user message immediately (with attachments if any)
    const userMsg: NormalizedMessage = {
      role: 'user',
      content: [{ type: 'text', text: message }],
      timestamp: Date.now(),
      id: crypto.randomUUID()
    }
    appendMessage(userMsg)

    // Subscribe to chat events
    const unsubscribe = client.on('chat', (frame) => {
      if (frame.type === 'event' && frame.event === 'chat') {
        const payload = frame.payload as any
        if (payload.state === 'delta') {
          // Update streaming text
          updateStream(payload.text ?? '', payload.runId, payload.thinkingState)
        } else if (payload.state === 'final') {
          // Final response received
          clearStream()
          setChatSending(false)
          setThinking(false)
          // Normalize content: handle both direct content and message.content format
          let content = payload.content
          if (!content && payload.message?.content) {
            content = payload.message.content
          }
          const assistantMsg: NormalizedMessage = {
            role: 'assistant',
            content: content ?? [{ type: 'text', text: '' }],
            timestamp: payload.timestamp ?? Date.now(),
            id: payload.id
          }
          appendMessage(assistantMsg)
          // Unsubscribe after final
          unsubscribe()
          setCurrentChatUnsubscribe(null)
        } else if (payload.state === 'aborted') {
          clearStream()
          setChatSending(false)
          unsubscribe()
          setCurrentChatUnsubscribe(null)
        } else if (payload.state === 'error') {
          clearStream()
          setChatSending(false)
          unsubscribe()
          setCurrentChatUnsubscribe(null)
        }
      }
    })

    setCurrentChatUnsubscribe(unsubscribe)

    try {
      await client.sendChat(message)
    } catch (e) {
      console.error('[OpenClawChat] Failed to send:', e)
      setChatSending(false)
      clearStream()
      unsubscribe()
      setCurrentChatUnsubscribe(null)
    }
  }, [client, chatMessage, setChatMessage, setChatSending, clearStream, clearToolStream, appendMessage, updateStream])

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
        for (const msg of messages) {
          appendMessage(msg)
        }
      } else {
        console.warn("[OpenClawChat] History load returned error:", result)
      }
    } catch (e) {
      console.warn("[OpenClawChat] Failed to load history:", e)
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
