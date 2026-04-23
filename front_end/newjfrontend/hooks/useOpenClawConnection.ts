/**
 * Hook for OpenClaw WebSocket connection lifecycle.
 *
 * Manages connect/disconnect, event subscription, and session switching.
 * Note: connect() is called by the parent component (page.tsx), not here.
 */

import { useEffect, useCallback, useRef } from "react"
import { useConnectionStore } from "@/stores/openclawConnectionStore"
import { useChatStore } from "@/stores/openclawChatStore"
import { useSessionsStore } from "@/stores/openclawSessionsStore"
import { useAgentsStore } from "@/stores/openclawAgentsStore"
import type { AgentEventPayload, ToolsCatalogResult } from "@/lib/openclaw/types"

export function useOpenClawConnection() {
  const connect = useConnectionStore((s) => s.connect)
  const disconnect = useConnectionStore((s) => s.disconnect)
  const client = useConnectionStore((s) => s.client)
  const setConnected = useConnectionStore((s) => s.setConnected)

  const addToolStreamEntry = useChatStore((s) => s.addToolStreamEntry)

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

  // Subscribe to events when client is available
  useEffect(() => {
    if (!client) return

    // NOTE: chat events (delta/final) are handled exclusively by useOpenClawChat.
    // Do not add a chat listener here — it would cause duplicate messages.

    // ─── Agent/tool stream events ───────────────────────────────────────

    const unsubAgent = client.on("agent", (frame) => {
      const payload = frame.payload as AgentEventPayload
      if (!payload || payload.stream !== "tool") return

      const data = payload.data ?? {}
      const name = data.name as string | undefined
      const toolCallId = (data.toolCallId as string | undefined) ?? `${payload.runId}-${payload.seq}`
      if (!name) return

      if (data.phase === "start") {
        addToolStreamEntry({
          toolCallId,
          name,
          args: data.args,
          kind: "call",
        })
      } else if (data.phase === "result") {
        const result = data.result
        addToolStreamEntry({
          toolCallId,
          name,
          text: result
            ? (typeof result === "string" ? result : JSON.stringify(result, null, 2))
            : "(completed)",
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
