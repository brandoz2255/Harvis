/**
 * Harvis workspace data layer — thin wrappers over the backend's existing
 * `/api/workspace/*` router (python_back_end/workspace/workspace_router.py).
 * Same-origin cookie auth: the web build is served from `/hermes/` behind the
 * same nginx that fronts `/api/`, so no token plumbing is needed here.
 */

export interface WorkspaceRun {
  id: string
  session_id: null | string
  task_brief: string
  status: string
  parent_run_id: null | string
  started_at: null | string
  completed_at: null | string
  duration_ms: null | number
  event_count: number
  tool_calls: number
  final_summary: null | string
  error_message: null | string
  model_name: null | string
  prompt_tokens: null | number
  completion_tokens: null | number
  child_count: number
}

export interface WorkspaceProvider {
  id: string
  label: string
  status: string
  models: string[]
  reason?: null | string
}

export interface WorkspaceEvent {
  seq?: number
  type: string
  payload: Record<string, unknown>
}

export interface LaunchResult {
  workspace_id: string
  session_id: string
  status: string
}

/** Any Harvis backend route (`/api/...`), JSON in and out; FormData bodies keep their own content type. */
export async function harvisApi<T>(path: string, init?: RequestInit): Promise<T> {
  const json = !(init?.body instanceof FormData)

  const res = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: { ...(json ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers ?? {}) }
  })

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`

    try {
      const body = (await res.json()) as { detail?: unknown }

      if (typeof body.detail === 'string') {
        detail = body.detail
      }
    } catch {
      // non-JSON error body: keep the status line
    }

    throw new Error(detail)
  }

  return (await res.json()) as T
}

const call = <T>(path: string, init?: RequestInit) => harvisApi<T>(`/api/workspace${path}`, init)

export const runsKey = ['harvis', 'workspace', 'runs'] as const
export const providersKey = ['harvis', 'workspace', 'providers'] as const
export const eventsKey = (id: string) => ['harvis', 'workspace', 'events', id] as const

export const fetchRuns = () => call<{ runs: WorkspaceRun[] }>('/history?top_level=1').then(r => r.runs ?? [])

export const fetchProviders = () => call<{ providers: WorkspaceProvider[] }>('/providers').then(r => r.providers ?? [])

export const fetchEvents = (id: string) =>
  call<{ events: { seq: number; event_type: string; payload: unknown }[] }>(
    `/run/${encodeURIComponent(id)}/events`
  ).then(r => (r.events ?? []).map(e => ({ seq: e.seq, type: e.event_type, payload: asRecord(e.payload) })))

export const launchRun = (body: { task_brief: string; agent_id: string; model_name: string }) =>
  call<LaunchResult>('/launch', { method: 'POST', body: JSON.stringify({ ...body, chat_history: [] }) })

export const cancelRun = (id: string) => call<unknown>(`/cancel/${encodeURIComponent(id)}`, { method: 'POST' })

export const rerunRun = (id: string) => call<LaunchResult>(`/run/${encodeURIComponent(id)}/rerun`, { method: 'POST' })

export const decideAction = (runId: string, actionId: string, approve: boolean) =>
  call<unknown>(
    `/run/${encodeURIComponent(runId)}/action/${encodeURIComponent(actionId)}/${approve ? 'approve' : 'deny'}`,
    { method: 'POST' }
  )

// asyncpg hands jsonb back as a string, so payloads may arrive double-encoded.
function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try {
      return asRecord(JSON.parse(value))
    } catch {
      return { message: value }
    }
  }

  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

/** Live SSE tail of a run. The server replays stored events first, then streams
 *  new ones and closes with `stream_end`. Returns an unsubscribe. */
export function streamRun(id: string, onEvent: (event: WorkspaceEvent) => void, onEnd: () => void): () => void {
  const source = new EventSource(`/api/workspace/stream/${encodeURIComponent(id)}`, { withCredentials: true })

  source.onmessage = message => {
    let data: Record<string, unknown>

    try {
      data = asRecord(JSON.parse(message.data as string))
    } catch {
      return
    }

    const type = typeof data.type === 'string' ? data.type : 'log'

    if (type === 'stream_end') {
      source.close()
      onEnd()

      return
    }

    const { seq, type: _type, ...payload } = data
    onEvent({ seq: typeof seq === 'number' ? seq : undefined, type, payload })
  }

  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      onEnd()
    }
  }

  return () => source.close()
}

export const ACTIVE_STATUSES = new Set(['running', 'pending', 'queued', 'awaiting_approval'])
export const FAILED_STATUSES = new Set(['failed', 'error', 'cancelled', 'orphaned', 'interrupted'])
