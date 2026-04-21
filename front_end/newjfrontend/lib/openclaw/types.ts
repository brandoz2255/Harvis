/**
 * OpenClaw Gateway JSON-RPC types for newjfrontend.
 *
 * Adapted from openclaw/openclaw/ui/src/ui/types.ts
 */

// ─── WebSocket Frame Types ───────────────────────────────────────────────────

export type GatewayEventFrame = {
  type: "event"
  event: string
  payload?: unknown
  seq?: number
}

export type GatewayResponseFrame = {
  type: "res"
  id: string
  ok: boolean
  payload?: unknown
  error?: { code: string; message: string; details?: unknown }
}

export type GatewayRequestFrame = {
  type: "req"
  id: string
  method: string
  params?: Record<string, unknown>
}

export type GatewayFrame = GatewayEventFrame | GatewayResponseFrame | GatewayRequestFrame

// ─── Connection Types ────────────────────────────────────────────────────────

export type GatewayHelloOk = {
  type: "hello-ok"
  protocol: number
  server?: { version?: string; connId?: string }
  features?: { methods?: string[]; events?: string[] }
  snapshot?: unknown
  auth?: {
    deviceToken?: string
    role?: string
    scopes?: string[]
    issuedAtMs?: number
  }
  policy?: { tickIntervalMs?: number }
}

export type GatewayConnectRequest = {
  minProtocol: number
  maxProtocol: number
  client: { id: string; version: string; platform: string; mode: string }
  role: string
  scopes: string[]
  auth: { token: string }
  device: {
    id: string
    publicKey: string
    signature: string
    signedAt: number
    nonce: string
  }
}

export type GatewayErrorInfo = {
  code: string
  message: string
  details?: unknown
}

export class GatewayRequestError extends Error {
  readonly gatewayCode: string
  readonly details?: unknown

  constructor(error: GatewayErrorInfo) {
    super(error.message)
    this.name = "GatewayRequestError"
    this.gatewayCode = error.code
    this.details = error.details
  }
}

// ─── Chat Types ──────────────────────────────────────────────────────────────

export type ChatMessageContentItem = {
  type: "text" | "tool_call" | "tool_result"
  text?: string
  name?: string
  args?: unknown
}

export type NormalizedMessage = {
  role: string
  content: ChatMessageContentItem[]
  timestamp: number
  id?: string
}

export type MessageGroup = {
  kind: "group"
  key: string
  role: string
  messages: Array<{ message: NormalizedMessage; key: string }>
  timestamp: number
  isStreaming: boolean
}

export type ToolCard = {
  kind: "call" | "result"
  name: string
  args?: unknown
  text?: string
}

export type ChatEventPayload = {
  runId?: string
  sessionKey?: string
  state: "delta" | "final" | "aborted" | "error"
  message?: NormalizedMessage
  text?: string
  thinking?: string
  thinkingState?: string
}

export type AgentEventPayload = {
  runId?: string
  toolCallId?: string
  name?: string
  args?: unknown
  result?: unknown
  text?: string
  state?: "start" | "delta" | "end"
  seq?: number
}

export type ChatAttachment = {
  name: string
  type: string
  data: string // base64
}

// ─── Session Types ───────────────────────────────────────────────────────────

export type GatewaySessionRow = {
  key: string
  kind: "direct" | "group" | "global" | "unknown"
  label?: string
  displayName?: string
  surface?: string
  subject?: string
  room?: string
  space?: string
  updatedAt: number | null
  sessionId?: string
  systemSent?: boolean
  abortedLastRun?: boolean
  thinkingLevel?: string
  verboseLevel?: string
  reasoningLevel?: string
  elevatedLevel?: string
  inputTokens?: number
  outputTokens?: number
  totalTokens?: number
  model?: string
  modelProvider?: string
  contextTokens?: number
}

export type SessionsListResult = {
  ts: number
  path: string
  count: number
  defaults: { model: string | null; contextTokens: number | null }
  sessions: GatewaySessionRow[]
}

export type SessionsPatchResult = {
  ok: true
  path: string
  key: string
  entry: {
    sessionId: string
    updatedAt?: number
    thinkingLevel?: string
    verboseLevel?: string
    reasoningLevel?: string
    elevatedLevel?: string
  }
}

export type SessionsResetResult = { ok: true; path: string; key: string }
export type SessionsDeleteResult = { ok: true; path: string; key: string }

// ─── Agent Types ─────────────────────────────────────────────────────────────

export type GatewayAgentRow = {
  id: string
  name?: string
  identity?: {
    name?: string
    theme?: string
    emoji?: string
    avatar?: string
    avatarUrl?: string
  }
}

export type AgentsListResult = {
  defaultId: string
  mainKey: string
  scope: string
  agents: GatewayAgentRow[]
}

export type AgentIdentityResult = {
  agentId: string
  name: string
  avatar: string
  emoji?: string
}

export type AgentFileEntry = {
  name: string
  path: string
  missing: boolean
  size?: number
  updatedAtMs?: number
  content?: string
}

export type AgentsFilesListResult = {
  agentId: string
  workspace: string
  files: AgentFileEntry[]
}

export type AgentsFilesGetResult = {
  agentId: string
  workspace: string
  file: AgentFileEntry
}

export type AgentsFilesSetResult = {
  ok: true
  agentId: string
  workspace: string
  file: AgentFileEntry
}

// ─── Tool & Skill Types ──────────────────────────────────────────────────────

export type ToolCatalogEntry = {
  id: string
  label: string
  description: string
  source: "core" | "plugin"
  pluginId?: string
  optional?: boolean
  defaultProfiles: Array<"minimal" | "coding" | "messaging" | "full">
}

export type ToolCatalogGroup = {
  id: string
  label: string
  source: "core" | "plugin"
  pluginId?: string
  tools: ToolCatalogEntry[]
}

export type ToolCatalogProfile = {
  id: "minimal" | "coding" | "messaging" | "full"
  label: string
}

export type ToolsCatalogResult = {
  agentId: string
  profiles: ToolCatalogProfile[]
  groups: ToolCatalogGroup[]
}

export type SkillStatusEntry = {
  name: string
  description: string
  source: string
  filePath: string
  baseDir: string
  skillKey: string
  bundled?: boolean
  primaryEnv?: string
  emoji?: string
  homepage?: string
  always: boolean
  disabled: boolean
  blockedByAllowlist: boolean
  eligible: boolean
  requirements: {
    bins: string[]
    env: string[]
    config: string[]
    os: string[]
  }
  missing: {
    bins: string[]
    env: string[]
    config: string[]
    os: string[]
  }
  configChecks: Array<{ path: string; satisfied: boolean }>
  install: Array<{ id: string; kind: string; label: string; bins: string[] }>
}

export type SkillStatusReport = {
  workspaceDir: string
  managedSkillsDir: string
  skills: SkillStatusEntry[]
}

// ─── Presence & Health ───────────────────────────────────────────────────────

export type PresenceEntry = {
  instanceId?: string | null
  host?: string | null
  ip?: string | null
  version?: string | null
  platform?: string | null
  deviceFamily?: string | null
  modelIdentifier?: string | null
  roles?: string[] | null
  scopes?: string[] | null
  mode?: string | null
  lastInputSeconds?: number | null
  reason?: string | null
  text?: string | null
  ts?: number | null
}
