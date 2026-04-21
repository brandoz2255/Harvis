/**
 * OpenClaw JSON-RPC WebSocket client for newjfrontend.
 *
 * Manages the WebSocket connection to the Harvis backend's OpenClaw gateway
 * proxy (/ws/openclaw). Provides request/response with UUID tracking,
 * event subscription, auto-reconnection, and message queuing.
 *
 * Protocol:
 *   Frontend → Backend: JSON-RPC frames via /ws/openclaw WebSocket
 *   Backend → Frontend: Relay of OpenClaw gateway frames
 *
 * The proxy handles all OpenClaw connect handshake, device identity,
 * and session management. Frontend just sends raw JSON-RPC frames.
 */

export type Frame =
  | { type: "req"; id: string; method: string; params?: Record<string, unknown> }
  | { type: "res"; id: string; ok: boolean; payload?: unknown; error?: { code: string; message: string } }
  | { type: "event"; event: string; payload?: unknown; seq?: number }

type EventCallback = (frame: Frame) => void
type ResponseResolver = (frame: Frame) => void

export type OpenClawClientOptions = {
  /** WebSocket URL (e.g., /ws/openclaw for proxied, or ws://host:18789 for direct) */
  url?: string
  /** Reconnection interval in ms (default: 3000) */
  reconnectInterval?: number
  /** Max reconnection attempts (default: Infinity) */
  maxReconnectAttempts?: number
  /** Session key for chat operations */
  sessionKey?: string
}

export class OpenClawClient {
  private ws: WebSocket | null = null
  private pending = new Map<string, { resolve: ResponseResolver; reject: (e: Error) => void }>()
  private eventListeners = new Map<string, Set<EventCallback>>()
  private reconnectAttempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private messageQueue: Frame[] = []
  private _connected = false
  private _sessionId: string | null = null
  private _hello: Frame["payload"] = null
  private reconnectAttemptsMax: number
  private reconnectInterval: number

  constructor(private options: OpenClawClientOptions = {}) {
    this.reconnectInterval = options.reconnectInterval ?? 3000
    this.reconnectAttemptsMax = options.maxReconnectAttempts ?? Infinity
    this._sessionId = options.sessionKey ?? null
  }

  get connected(): boolean {
    return this._connected
  }

  get sessionId(): string | null {
    return this._sessionId
  }

  get hello(): Frame["payload"] {
    return this._hello
  }

  /** Connect to the gateway proxy */
  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
      return
    }

    const url = this.options.url ?? "/ws/openclaw"
    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      this._connected = true
      this.reconnectAttempts = 0
      this._emit("connected", { type: "event", event: "connected", payload: {} })

      // Flush queued messages
      for (const msg of this.messageQueue) {
        this.ws?.send(JSON.stringify(msg))
      }
      this.messageQueue = []
    }

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const frame = JSON.parse(event.data as string) as Frame

        if (frame.type === "res") {
          const pending = this.pending.get(frame.id)
          if (pending) {
            this.pending.delete(frame.id)
            pending.resolve(frame)
          }
        } else if (frame.type === "event") {
          this._emit(frame.event, frame)
          this._emit("*", frame)
        }
      } catch (e) {
        console.error("[OpenClawClient] Failed to parse message:", e)
      }
    }

    this.ws.onclose = (event: CloseEvent) => {
      this._connected = false
      this._emit("disconnected", { type: "event", event: "disconnected", payload: { code: event.code, reason: event.reason } })

      // Try to reconnect
      if (this.reconnectAttempts < this.reconnectAttemptsMax) {
        this.reconnectAttempts++
        const delay = Math.min(this.reconnectInterval * Math.pow(1.5, this.reconnectAttempts - 1), 30000)
        this.reconnectTimer = setTimeout(() => this.connect(), delay)
      }
    }

    this.ws.onerror = (error: Event) => {
      console.error("[OpenClawClient] WebSocket error:", error)
    }
  }

  /** Disconnect from the gateway */
  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    // Reject all pending requests
    for (const [id, pending] of this.pending) {
      pending.reject(new Error("Connection closed"))
      this.pending.delete(id)
    }

    if (this.ws) {
      this.ws.close(1000, "Client disconnecting")
      this.ws = null
    }
    this._connected = false
  }

  /**
   * Send a JSON-RPC request and wait for response.
   * If not connected, queues the message for later.
   */
  async request(method: string, params?: Record<string, unknown>): Promise<Frame> {
    const id = crypto.randomUUID()

    const frame: Frame = {
      type: "req",
      id,
      method,
      params: params ?? {},
    }

    // Inject sessionKey if this is a chat operation
    if (method === "chat.send" && this._sessionId && params && !params.sessionKey) {
      params.sessionKey = this._sessionId
      params.idempotencyKey = params.idempotencyKey ?? crypto.randomUUID()
    }

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(frame))
    } else {
      this.messageQueue.push(frame)
    }

    return new Promise<Frame>((resolve, reject) => {
      this.pending.set(id, { resolve, reject })

      // Timeout after 60 seconds
      setTimeout(() => {
        const pending = this.pending.get(id)
        if (pending) {
          this.pending.delete(id)
          reject(new Error(`Request timeout: ${method}`))
        }
      }, 60000)
    })
  }

  /**
   * Send a chat message.
   * Convenience wrapper around request("chat.send", ...).
   */
  async sendChat(text: string, attachments?: Array<{ name: string; type: string; data: string }>): Promise<Frame> {
    return this.request("chat.send", {
      text,
      attachments,
    })
  }

  /**
   * Abort the current chat run.
   */
  async abortChat(runId?: string): Promise<Frame> {
    return this.request("chat.abort", { runId })
  }

  /**
   * Load chat history for the current session.
   */
  async loadChatHistory(limit = 200): Promise<Frame> {
    return this.request("chat.history", { limit })
  }

  /**
   * Load session list.
   */
  async listSessions(): Promise<Frame> {
    return this.request("sessions.list", {})
  }

  /**
   * Patch a session (e.g., change name, thinking level).
   */
  async patchSession(sessionKey: string, updates: Record<string, unknown>): Promise<Frame> {
    return this.request("sessions.patch", { sessionKey, updates })
  }

  /**
   * Delete a session.
   */
  async deleteSession(sessionKey: string): Promise<Frame> {
    return this.request("sessions.delete", { sessionKey })
  }

  /**
   * Reset a session (clear messages).
   */
  async resetSession(sessionKey: string): Promise<Frame> {
    return this.request("sessions.reset", { sessionKey })
  }

  /**
   * List agents.
   */
  async listAgents(): Promise<Frame> {
    return this.request("agents.list", {})
  }

  /**
   * Get agent files.
   */
  async listAgentFiles(agentId: string): Promise<Frame> {
    return this.request("agents.files.list", { agentId })
  }

  /**
   * Get agent identity.
   */
  async getAgentIdentity(agentId: string): Promise<Frame> {
    return this.request("agents.identity", { agentId })
  }

  /**
   * Get tools catalog.
   */
  async getToolsCatalog(): Promise<Frame> {
    return this.request("tools.catalog", {})
  }

  /**
   * Get skill status.
   */
  async getSkillStatus(): Promise<Frame> {
    return this.request("skills.status", {})
  }

  /**
   * Switch session.
   */
  async switchSession(sessionKey: string): void {
    this._sessionId = sessionKey
    this._emit("sessionChanged", { type: "event", event: "sessionChanged", payload: { sessionKey } })
  }

  // ─── Event System ────────────────────────────────────────────────────────

  /** Subscribe to an event type */
  on(event: string, callback: EventCallback): () => void {
    if (!this.eventListeners.has(event)) {
      this.eventListeners.set(event, new Set())
    }
    this.eventListeners.get(event)!.add(callback)

    // Return unsubscribe function
    return () => {
      this.eventListeners.get(event)?.delete(callback)
    }
  }

  /** Subscribe to all events */
  onAny(callback: EventCallback): () => void {
    return this.on("*", callback)
  }

  private _emit(event: string, frame: Frame): void {
    const listeners = this.eventListeners.get(event)
    if (listeners) {
      for (const cb of listeners) {
        try {
          cb(frame)
        } catch (e) {
          console.error(`[OpenClawClient] Error in event listener for "${event}":`, e)
        }
      }
    }
  }
}
