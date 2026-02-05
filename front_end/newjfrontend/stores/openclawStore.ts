"""
OpenClaw Store

Zustand store for managing OpenClaw instances and tasks.
"""

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
    
    // Instance actions
    setInstances: (instances) => set({ instances }),
    
    selectInstance: (id) => set({ selectedInstanceId: id }),
    
    addInstance: (instance) =>
      set((state) => {
        state.instances.push(instance)
      }),
    
    updateInstance: (id, updates) =>
      set((state) => {
        const index = state.instances.findIndex((i) => i.id === id)
        if (index !== -1) {
          Object.assign(state.instances[index], updates)
        }
      }),
    
    removeInstance: (id) =>
      set((state) => {
        state.instances = state.instances.filter((i) => i.id !== id)
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
        const index = state.tasks.findIndex((t) => t.id === id)
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
        const task = state.tasks.find((t) => t.id === taskId)
        if (task && task.steps[stepIndex]) {
          Object.assign(task.steps[stepIndex], updates)
          // Recalculate progress
          const completed = task.steps.filter((s) => s.status === 'completed').length
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
        state.tasks = state.tasks.filter((t) => t.id !== id)
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
        state.events = state.events.filter((e) => e.taskId !== taskId)
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
