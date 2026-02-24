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
  confidence: number
  task_type: string | null
  task_type_label: string
  task_brief: string
  reason: string
}

export type WorkspaceLogEventType =
  | 'token'
  | 'tool_call'
  | 'tool_result'
  | 'log'
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
  activeTab: 'progress' | 'preview' | 'logs' | 'artifacts'

  // Harvis Workspace session state
  suggestion: WorkspaceSuggestion | null
  workspaceId: string | null
  workspaceSessionId: string | null   // persists across launches for same user (resumable)
  logEvents: WorkspaceLogEvent[]
  finalSummary: string
  sseAbortController: AbortController | null

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
  setActiveTab: (tab: 'progress' | 'preview' | 'logs' | 'artifacts') => void

  // Harvis Workspace actions
  setSuggestion: (suggestion: WorkspaceSuggestion | null) => void
  setWorkspaceId: (id: string | null) => void
  setWorkspaceSessionId: (id: string | null) => void
  addLogEvent: (event: Omit<WorkspaceLogEvent, 'id' | 'timestamp'>) => void
  clearLogEvents: () => void
  setFinalSummary: (summary: string) => void
  setSseAbortController: (controller: AbortController | null) => void
  closeWorkspace: () => void

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
    activeTab: 'progress',

    // Harvis Workspace initial state
    suggestion: null,
    workspaceId: null,
    workspaceSessionId: null,
    logEvents: [],
    finalSummary: '',
    sseAbortController: null,

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
        state.isChatMinimized = active
      }),

    setChatMinimized: (minimized) => set({ isChatMinimized: minimized }),

    setActiveTab: (tab) => set({ activeTab: tab }),

    // Harvis Workspace actions
    setSuggestion: (suggestion) => set({ suggestion }),

    setWorkspaceId: (id) => set({ workspaceId: id }),

    setWorkspaceSessionId: (id) => set({ workspaceSessionId: id }),

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
        state.logEvents = []
        state.finalSummary = ''
        state.sseAbortController = null
        state.activeTab = 'progress'
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
