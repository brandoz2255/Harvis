/**
 * OpenClaw Store
 * 
 * Zustand store for managing OpenClaw instances and tasks.
 */

import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

// Types
export interface OpenClawInstance {
  id: string
  name: string
  vmType: 'virtualbox' | 'docker' | 'cloud'
  status: 'offline' | 'connecting' | 'online' | 'busy' | 'error'
  lastConnectedAt?: string
  vmIp?: string
  vmPort?: number
}

export interface TaskStep {
  index: number
  description: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  result?: string
  errorMessage?: string
  startedAt?: string
  completedAt?: string
  screenshots?: string[]
}

export interface OpenClawTask {
  id: string
  instanceId: string
  sessionId?: string
  description: string
  status: 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'
  steps: TaskStep[]
  currentStep: number
  result?: string
  errorMessage?: string
  startedAt?: string
  completedAt?: string
  createdAt: string
  progressPercentage: number
}

export interface OpenClawEvent {
  id: string
  taskId: string
  type: string
  payload: any
  createdAt: string
}

// ─── Harvis Workspace (OpenClaw backend integration) ─────────────────────────

export interface WorkspaceSuggestion {
  should_suggest: boolean
  auto_launch?: boolean          // true → 3-2-1 countdown auto-launch
  confidence: number
  task_type: string | null
  task_type_label: string
  task_brief: string
  reason: string
  model?: 'local' | 'kimi' | 'nvidia-kimi' | 'cloud-ollama'  // preferred model from LLM signal
}

// ─── Kubectl Approval ─────────────────────────────────────────────────────────

export interface KubectlPendingCommand {
  approval_id: string
  command: string
  namespace?: string
  timeout: number
  requested_at: string   // ISO-8601
  status: 'pending'
}

export type WorkspaceLogEventType =
  | 'token'
  | 'tool_call'
  | 'tool_result'
  | 'log'
  | 'agent_start'
  | 'agent_end'
  | 'done'
  | 'cancelled'
  | 'error'
  | 'stream_end'

export interface WorkspaceLogEvent {
  id: string
  type: WorkspaceLogEventType
  // token
  content?: string
  // tool_call
  tool?: string
  args?: Record<string, unknown>
  // tool_result
  output?: string
  success?: boolean
  // log / done / cancelled / error
  message?: string
  summary?: string
  timestamp: number
  // sub-agent tracking — populated by backend when OpenClaw emits agent events
  run_id?: string
  agent_label?: string  // "Agent" | "Sub-Agent 1" | "Sub-Agent 2" …
  // agent lifecycle (agent_start / agent_end events)
  model?: string | null  // model name on agent_start
  parent_run_id?: string | null  // parent agent's run_id (null for root agent)
}

export interface Screenshot {
  id: string
  taskId: string
  stepIndex?: number
  caption?: string
  url: string
  thumbnailUrl?: string
  width: number
  height: number
  takenAt: string
}

/** Server reports a Discord-started workspace; used for UI hint + auto-follow. */
export interface DiscordExternalWorkspaceHint {
  workspace_id: string
  task_brief: string
}

interface OpenClawState {
  // Instances
  instances: OpenClawInstance[]
  selectedInstanceId: string | null

  // Tasks
  tasks: OpenClawTask[]
  currentTask: OpenClawTask | null

  // Events
  events: OpenClawEvent[]

  // Screenshots
  screenshots: Screenshot[]
  currentScreenshot: Screenshot | null

  // UI State
  isWorkspaceActive: boolean
  isChatMinimized: boolean
  activeTab: 'dashboard' | 'playbooks' | 'logs' | 'agents' | 'github'
  selectedAgentId: string | null

  // Harvis Workspace session state
  suggestion: WorkspaceSuggestion | null
  workspaceId: string | null
  workspaceSessionId: string | null   // persists across launches for same user (resumable)
  workspaceModel: 'local' | 'kimi' | 'nvidia-kimi' | 'cloud-ollama'
  workspaceModelName: string
  logEvents: WorkspaceLogEvent[]
  finalSummary: string
  sseAbortController: AbortController | null
  /** Non-null while GET /active reports a running Discord workspace for this user. */
  discordExternalWorkspace: DiscordExternalWorkspaceHint | null

  // Kubectl approval state
  kubectlPending: KubectlPendingCommand[]

  // Actions
  setInstances: (instances: OpenClawInstance[]) => void
  selectInstance: (id: string | null) => void
  addInstance: (instance: OpenClawInstance) => void
  updateInstance: (id: string, updates: Partial<OpenClawInstance>) => void
  removeInstance: (id: string) => void

  setTasks: (tasks: OpenClawTask[]) => void
  setCurrentTask: (task: OpenClawTask | null) => void
  addTask: (task: OpenClawTask) => void
  updateTask: (id: string, updates: Partial<OpenClawTask>) => void
  updateTaskStep: (taskId: string, stepIndex: number, updates: Partial<TaskStep>) => void
  removeTask: (id: string) => void

  addEvent: (event: OpenClawEvent) => void
  clearEvents: (taskId: string) => void

  addScreenshot: (screenshot: Screenshot) => void
  setCurrentScreenshot: (screenshot: Screenshot | null) => void

  setWorkspaceActive: (active: boolean) => void
  setChatMinimized: (minimized: boolean) => void
  setActiveTab: (tab: 'dashboard' | 'playbooks' | 'logs' | 'agents' | 'github') => void
  setSelectedAgentId: (id: string | null) => void

  // Harvis Workspace actions
  setSuggestion: (suggestion: WorkspaceSuggestion | null) => void
  setWorkspaceId: (id: string | null) => void
  setWorkspaceSessionId: (id: string | null) => void
  setWorkspaceModel: (model: 'local' | 'kimi' | 'nvidia-kimi' | 'cloud-ollama') => void
  setWorkspaceModelName: (name: string) => void
  addLogEvent: (event: Omit<WorkspaceLogEvent, 'id' | 'timestamp'>) => void
  clearLogEvents: () => void
  setFinalSummary: (summary: string) => void
  setSseAbortController: (controller: AbortController | null) => void
  closeWorkspace: () => void
  setDiscordExternalWorkspace: (hint: DiscordExternalWorkspaceHint | null) => void
  /** Attach SSE timeline for an existing run (e.g. Discord or manual “open”). */
  attachToWorkspaceStream: (workspaceId: string) => Promise<void>

  // Kubectl approval actions
  setKubectlPending: (pending: KubectlPendingCommand[]) => void
  removeKubectlPending: (approvalId: string) => void

  // Computed
  getInstanceById: (id: string) => OpenClawInstance | undefined
  getTaskById: (id: string) => OpenClawTask | undefined
  getEventsForTask: (taskId: string) => OpenClawEvent[]
  getScreenshotsForTask: (taskId: string) => Screenshot[]
  getOnlineInstances: () => OpenClawInstance[]
}

export const useOpenClawStore = create<OpenClawState>()(
  immer((set, get) => ({
    // Initial state
    instances: [],
    selectedInstanceId: null,
    tasks: [],
    currentTask: null,
    events: [],
    screenshots: [],
    currentScreenshot: null,
    isWorkspaceActive: false,
    isChatMinimized: false,
    activeTab: 'dashboard' as const,
    selectedAgentId: null,

    // Harvis Workspace initial state
    suggestion: null,
    workspaceId: null,
    workspaceSessionId: null,
    workspaceModel: 'local' as const,
    workspaceModelName: '',
    logEvents: [],
    finalSummary: '',
    sseAbortController: null,
    discordExternalWorkspace: null,
    kubectlPending: [],

    // Instance actions
    setInstances: (instances) => set({ instances }),

    selectInstance: (id) => set({ selectedInstanceId: id }),

    addInstance: (instance) =>
      set((state) => {
        state.instances.push(instance)
      }),

    updateInstance: (id, updates) =>
      set((state) => {
        const index = state.instances.findIndex((i: OpenClawInstance) => i.id === id)
        if (index !== -1) {
          Object.assign(state.instances[index], updates)
        }
      }),

    removeInstance: (id) =>
      set((state) => {
        state.instances = state.instances.filter((i: OpenClawInstance) => i.id !== id)
      }),

    // Task actions
    setTasks: (tasks) => set({ tasks }),

    setCurrentTask: (task) => set({ currentTask: task }),

    addTask: (task) =>
      set((state) => {
        state.tasks.push(task)
        if (!state.currentTask) {
          state.currentTask = task
        }
      }),

    updateTask: (id, updates) =>
      set((state) => {
        const index = state.tasks.findIndex((t: OpenClawTask) => t.id === id)
        if (index !== -1) {
          Object.assign(state.tasks[index], updates)
          // Update currentTask if it's the same
          if (state.currentTask?.id === id) {
            Object.assign(state.currentTask, updates)
          }
        }
      }),

    updateTaskStep: (taskId, stepIndex, updates) =>
      set((state) => {
        const task = state.tasks.find((t: OpenClawTask) => t.id === taskId)
        if (task && task.steps[stepIndex]) {
          Object.assign(task.steps[stepIndex], updates)
          // Recalculate progress
          const completed = task.steps.filter((s: TaskStep) => s.status === 'completed').length
          task.progressPercentage = (completed / task.steps.length) * 100

          // Update currentTask if it's the same
          if (state.currentTask?.id === taskId) {
            Object.assign(state.currentTask.steps[stepIndex], updates)
            state.currentTask.progressPercentage = task.progressPercentage
          }
        }
      }),

    removeTask: (id) =>
      set((state) => {
        state.tasks = state.tasks.filter((t: OpenClawTask) => t.id !== id)
        if (state.currentTask?.id === id) {
          state.currentTask = null
        }
      }),

    // Event actions
    addEvent: (event) =>
      set((state) => {
        state.events.push(event)
      }),

    clearEvents: (taskId) =>
      set((state) => {
        state.events = state.events.filter((e: OpenClawEvent) => e.taskId !== taskId)
      }),

    // Screenshot actions
    addScreenshot: (screenshot) =>
      set((state) => {
        state.screenshots.push(screenshot)
        state.currentScreenshot = screenshot
      }),

    setCurrentScreenshot: (screenshot) => set({ currentScreenshot: screenshot }),

    // UI actions
    setWorkspaceActive: (active) =>
      set((state) => {
        state.isWorkspaceActive = active
        // Don't auto-minimize chat — let user see both panels in split view
        if (!active) state.isChatMinimized = false
      }),

    setChatMinimized: (minimized) => set({ isChatMinimized: minimized }),

    setActiveTab: (tab) => set({ activeTab: tab }),

    setSelectedAgentId: (id) => set({ selectedAgentId: id }),

    // Harvis Workspace actions
    setSuggestion: (suggestion) => set({ suggestion }),

    setWorkspaceId: (id) => set({ workspaceId: id }),

    setWorkspaceSessionId: (id) => set({ workspaceSessionId: id }),

    setWorkspaceModel: (model) => set({ workspaceModel: model }),

    setWorkspaceModelName: (name) => set({ workspaceModelName: name }),

    addLogEvent: (event) =>
      set((state) => {
        state.logEvents.push({
          ...event,
          id: `evt-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          timestamp: Date.now(),
        })
      }),

    clearLogEvents: () => set({ logEvents: [] }),

    setFinalSummary: (summary) => set({ finalSummary: summary }),

    setSseAbortController: (controller) => set({ sseAbortController: controller }),

    setDiscordExternalWorkspace: (hint) => set({ discordExternalWorkspace: hint }),

    attachToWorkspaceStream: async (workspaceId: string) => {
      if (typeof window === 'undefined') return
      const token = localStorage.getItem('token')
      if (!token || !workspaceId) return

      // #region agent log
      try {
        fetch('http://127.0.0.1:7532/ingest/9269ee65-762c-4e4d-9bef-0cd2be96389e', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'd007eb' },
          body: JSON.stringify({
            sessionId: 'd007eb',
            location: 'openclawStore.ts:attachToWorkspaceStream:start',
            message: 'attach_workspace_stream_start',
            data: { workspaceId },
            runId: 'run_workspace_follow_click',
            hypothesisId: 'H_active_orphan',
            timestamp: Date.now(),
          }),
        }).catch(() => {})
      } catch {
        /* ignore */
      }
      // #endregion

      set((state) => {
        state.sseAbortController?.abort()
        state.logEvents = []
        state.finalSummary = ''
        state.activeTab = 'dashboard'
        state.isWorkspaceActive = true
        state.workspaceId = workspaceId
        state.workspaceSessionId = `ws-${workspaceId}`
      })

      const controller = new AbortController()
      set((state) => {
        state.sseAbortController = controller
      })

      get().addLogEvent({
        type: 'log',
        message: `Attaching to workspace ${workspaceId}…`,
        agent_label: 'harvis',
      })

      let streamRes: Response
      try {
        streamRes = await fetch(`/api/workspace/stream/${workspaceId}`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        })
      } catch {
        // #region agent log
        try {
          fetch('http://127.0.0.1:7532/ingest/9269ee65-762c-4e4d-9bef-0cd2be96389e', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'd007eb' },
            body: JSON.stringify({
              sessionId: 'd007eb',
              location: 'openclawStore.ts:attachToWorkspaceStream:fetch',
              message: 'attach_workspace_stream_fetch_failed',
              data: { workspaceId },
              runId: 'run_workspace_follow_click',
              hypothesisId: 'H_active_orphan',
              timestamp: Date.now(),
            }),
          }).catch(() => {})
        } catch {
          /* ignore */
        }
        // #endregion
        get().addLogEvent({ type: 'error', message: 'SSE connection failed.' })
        set({ workspaceId: null, isWorkspaceActive: false })
        return
      }

      // #region agent log
      try {
        fetch('http://127.0.0.1:7532/ingest/9269ee65-762c-4e4d-9bef-0cd2be96389e', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'd007eb' },
          body: JSON.stringify({
            sessionId: 'd007eb',
            location: 'openclawStore.ts:attachToWorkspaceStream:response',
            message: 'attach_workspace_stream_response',
            data: { workspaceId, status: streamRes.status, ok: streamRes.ok, hasBody: Boolean(streamRes.body) },
            runId: 'run_workspace_follow_click',
            hypothesisId: 'H_active_orphan',
            timestamp: Date.now(),
          }),
        }).catch(() => {})
      } catch {
        /* ignore */
      }
      // #endregion

      // Handle 404 or other error responses - clear stale workspace state
      if (!streamRes.ok) {
        if (streamRes.status === 404) {
          get().addLogEvent({ type: 'error', message: `Workspace ${workspaceId} not found (may have expired).` })
        } else {
          get().addLogEvent({ type: 'error', message: `Stream error: HTTP ${streamRes.status}` })
        }
        set({ workspaceId: null, isWorkspaceActive: false, sseAbortController: null })
        return
      }

      if (!streamRes.body) {
        get().addLogEvent({ type: 'error', message: 'No SSE stream body returned.' })
        set({ workspaceId: null, isWorkspaceActive: false })
        return
      }

      const reader = streamRes.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const readLoop = async () => {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const event = JSON.parse(line.slice(6))
              if (event.type === 'stream_end') break
              if (event.type === 'done') {
                get().setFinalSummary(event.summary ?? '')
              }
              get().addLogEvent(event)
            } catch {
              // ignore malformed SSE
            }
          }
        }
      }

      readLoop().catch(() => {
        /* stream closed */
      })
    },

    closeWorkspace: () =>
      set((state) => {
        // Abort any active SSE connection
        if (state.sseAbortController) {
          state.sseAbortController.abort()
        }
        state.isWorkspaceActive = false
        state.isChatMinimized = false
        state.suggestion = null
        state.workspaceId = null
        // Keep workspaceModel and workspaceModelName — they're persisted to DB
        // and will be restored on next mount from /api/user/openclaw-config.
        state.workspaceSessionId = null   // always fresh session on next launch
        state.logEvents = []
        state.finalSummary = ''
        state.sseAbortController = null
        state.activeTab = 'dashboard'
        state.selectedAgentId = null
        state.kubectlPending = []
      }),

    // Kubectl approval actions
    setKubectlPending: (pending) => set({ kubectlPending: pending }),

    removeKubectlPending: (approvalId) =>
      set((state) => {
        state.kubectlPending = state.kubectlPending.filter(
          (c) => c.approval_id !== approvalId
        )
      }),

    // Computed
    getInstanceById: (id) => get().instances.find((i) => i.id === id),

    getTaskById: (id) => get().tasks.find((t) => t.id === id),

    getEventsForTask: (taskId) =>
      get().events.filter((e) => e.taskId === taskId),

    getScreenshotsForTask: (taskId) =>
      get().screenshots.filter((s) => s.taskId === taskId),

    getOnlineInstances: () =>
      get().instances.filter(
        (i) => i.status === 'online' || i.status === 'busy'
      ),
  }))
)
