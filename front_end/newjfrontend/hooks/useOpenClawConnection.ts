/**
 * Hook for OpenClaw WebSocket connection lifecycle.
 *
 * Manages connect/disconnect, event subscription, and session switching.
 */

import { useEffect, useCallback, useRef } from "react"
import { useConnectionStore } from "@/stores/openclawConnectionStore"
import { useChatStore } from "@/stores/openclawChatStore"
import { useSessionsStore } from "@/stores/openclawSessionsStore"
import { useAgentsStore } from "@/stores/openclawAgentsStore"
import type { NormalizedMessage, MessageGroup, ChatEventPayload, AgentEventPayload } from "@/lib/openclaw/types"

export function useOpenClawConnection() {
  const connect = useConnectionStore((s) => s.connect)
  const disconnect = useConnectionStore((s) => s.disconnect)
  const client = useConnectionStore((s) => s.client)
  const setConnected = useConnectionStore((s) => s.setConnected)

  const setMessages = useChatStore((s) => s.setMessages)
  const appendMessage = useChatStore((s) => s.appendMessage)
  const updateStream = useChatStore((s) => s.updateStream)
  const clearStream = useChatStore((s) => s.clearStream)
  const addToolStreamEntry = useChatStore((s) => s.addToolStreamEntry)
  const clearToolStream = useChatStore((s) => s.clearToolStream)
  const setChatSending = useChatStore((s) => s.setChatSending)

  const setSessions = useSessionsStore((s) => s.setSessions)

  const setAgents = useAgentsStore((s) => s.setAgents)
  const setAgentFiles = useAgentsStore((s) => s.setAgentFiles)
  const setToolCatalog = useAgentsStore((s) => s.setToolCatalog)
  const setSkills = useAgentsStore((s) => s.setSkills)

  // Track if effect has been mounted to avoid stale closures
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  // Connect on mount
  useEffect(() => {
    connect()

    if (!client) return

    // ─── Chat events ────────────────────────────────────────────────────

    const unsubChat = client.on("chat", (frame) => {
      const payload = frame.payload as ChatEventPayload
      if (!payload) return

      if (payload.state === "delta") {
        updateStream(
          payload.text ?? "",
          payload.runId,
          payload.thinkingState ?? null,
        )
      } else if (payload.state === "final") {
        clearStream()
        clearToolStream()

        if (payload.message) {
          appendMessage(payload.message as NormalizedMessage)
        }

        setChatSending(false)
      } else if (payload.state === "aborted") {
        clearStream()
        clearToolStream()
        setChatSending(false)
      } else if (payload.state === "error") {
        clearStream()
        clearToolStream()
        setChatSending(false)
      }
    })

    // ─── Agent/tool stream events ───────────────────────────────────────

    const unsubAgent = client.on("agent", (frame) => {
      const payload = frame.payload as AgentEventPayload
      if (!payload) return

      if (payload.name && payload.state === "start") {
        addToolStreamEntry({
          toolCallId: payload.toolCallId ?? crypto.randomUUID(),
          name: payload.name,
          args: payload.args,
          kind: "call",
        })
      } else if (payload.name && payload.state === "end") {
        addToolStreamEntry({
          toolCallId: payload.toolCallId ?? "",
          name: payload.name,
          text: payload.text ?? "",
          kind: "result",
        })
      }
    })

    // ─── Session list events ────────────────────────────────────────────

    const unsubSessions = client.on("sessions.list", (frame) => {
      if (frame.type !== "res" || !frame.ok) return
      const result = frame.payload as { sessions: any[] }
      if (result?.sessions) {
        setSessions({
          ts: Date.now(),
          path: "",
          count: result.sessions.length,
          defaults: { model: null, contextTokens: 0 },
          sessions: result.sessions,
        })
      }
    })

    // ─── Agents list events ─────────────────────────────────────────────

    const unsubAgents = client.on("agents.list", (frame) => {
      if (frame.type !== "res" || !frame.ok) return
      const result = frame.payload as any
      if (result?.agents) {
        setAgents({
          defaultId: result.defaultId || "",
          mainKey: result.mainKey || "",
          scope: result.scope || "",
          agents: result.agents,
        })
      }
    })

    // ─── Tools catalog events ───────────────────────────────────────────

    const unsubTools = client.on("tools.catalog", (frame) => {
      if (frame.type !== "res" || !frame.ok) return
      const result = frame.payload as ToolsCatalogResult
      if (result) {
        setToolCatalog(result)
      }
    })

    // ─── Skills events ──────────────────────────────────────────────────

    const unsubSkills = client.on("skills.status", (frame) => {
      if (frame.type !== "res" || !frame.ok) return
      const result = frame.payload as { workspaceDir: string; skills: any[] }
      if (result?.skills) {
        setSkills({
          workspaceDir: result.workspaceDir || "",
          managedSkillsDir: "",
          skills: result.skills,
        })
      }
    })

    // ─── Agent files events ─────────────────────────────────────────────

    const unsubFiles = client.on("agents.files.list", (frame) => {
      if (frame.type !== "res" || !frame.ok) return
      const result = frame.payload as { agentId: string; workspace: string; files: any[] }
      if (result?.files) {
        setAgentFiles({
          agentId: result.agentId,
          workspace: result.workspace,
          files: result.files,
        })
      }
    })

    return () => {
      unsubChat()
      unsubAgent()
      unsubSessions()
      unsubAgents()
      unsubTools()
      unsubSkills()
      unsubFiles()
    }
  }, [client])

  const isConnected = useConnectionStore((s) => s.connected)

  return {
    isConnected,
    connect,
    disconnect,
    client,
  }
}
