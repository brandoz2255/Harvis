/**
 * Harvis backend calls the Settings pages make directly: provider status, coding
 * engine credentials, and learned memory. Same-origin cookie auth, like the rest
 * of the web build. Credentials are only ever sent, never read back.
 */

import { reportUnauthorized } from '@/lib/harvis-session'

import { createSseParser, type PullEvent } from './pull-progress'

export async function harvisFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }
  })

  if (!res.ok) {
    if (res.status === 401) {
      reportUnauthorized()
    }

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

const post = <T>(path: string, body: unknown) => harvisFetch<T>(path, { method: 'POST', body: JSON.stringify(body) })

export interface CredentialStatus {
  saved: boolean
  verified: boolean
  auth_mode: string
  last_error: null | string
}

export interface FreeProvider {
  id: string
  label: string
  console_url: string
  note: string
  base_url?: string
  /** A server the user runs (OmniRoute): connect with the key field empty. */
  key_optional?: boolean
  auth: CredentialStatus
  /** Key-optional providers are kept as the user's own custom endpoint with this id. */
  endpoint_id?: null | string
  endpoint?: EndpointSummary | null
}

/** Stand-in credential a key-optional provider is connected with (free_providers.NO_KEY). */
export const NO_KEY = 'no-key'

export interface EndpointSummary {
  id: string
  name: string
  base_url: string
  model: string
  models: string[]
  has_api_key: boolean
  is_current: boolean
}

/** One row of /harvis/providers: a model source with the way to connect it. */
export interface HarvisProviderRow {
  id: string
  kind: 'local' | 'user-api-key'
  label: string
  status: string
  models: string[]
  reason?: null | string
  note: string
  base_url: string
  console_url: null | string
  auth: CredentialStatus | null
  /** user_api_keys provider name (kind user-api-key). */
  provider_name?: string
  /** The user's own copy of this source, when one is saved (kind local). */
  endpoint: EndpointSummary | null
  endpoint_id: null | string
}

export interface EndpointCheck {
  ok: boolean
  reachable: boolean
  models: string[]
  message: string
}

export interface CodingEngine {
  id: string
  label: string
  description: string
  container: string
  state: string
  needs_key: boolean
  auth: CredentialStatus | null
  supports_oauth: boolean
  hint: null | string
}

export interface MemoryEntry {
  id: number
  content: string
  source: string
  created_at: null | string
  /** Imported from a sandbox's USER.md; chats ignore it until the user keeps it. */
  pending?: boolean
}

export interface LearnSettings {
  memory: boolean
  skills: boolean
}

export const fetchHarvisProviders = () =>
  harvisFetch<{ providers: HarvisProviderRow[] }>('/hermes-api/api/harvis/providers').then(r => r.providers ?? [])

export const fetchFreeProviders = () =>
  harvisFetch<{ providers: FreeProvider[] }>('/hermes-api/api/harvis/free-providers').then(r => r.providers ?? [])

export const fetchEngines = () =>
  harvisFetch<{ engines: CodingEngine[] }>('/hermes-api/api/harvis/engines').then(r => r.engines ?? [])

/** Verifies the credential with the vendor and stores it encrypted; a failing one is kept with its error. */
export const connectCredential = (engine: string, credential: string, authMode = 'api_key') =>
  post<{ ok: boolean; error: null | string }>(`/api/owui/engine-auth/${encodeURIComponent(engine)}/verify`, {
    credential,
    auth_mode: authMode
  })

export const disconnectCredential = (engine: string) =>
  post<{ ok: boolean }>(`/api/owui/engine-auth/${encodeURIComponent(engine)}/disconnect`, {})

/** Moonshot keys are checked with Moonshot before they are stored (400 when rejected). */
export const saveUserApiKey = (providerName: string, apiKey: string) =>
  post<{ provider_name: string; is_active: boolean }>('/api/user/api-keys', {
    provider_name: providerName,
    api_key: apiKey,
    is_active: true
  })

export const deleteUserApiKey = (providerName: string) =>
  harvisFetch<unknown>(`/api/user/api-keys/${encodeURIComponent(providerName)}`, { method: 'DELETE' })

/** Reachability + model list for an OpenAI-compatible base URL; nothing is stored. */
export const checkEndpoint = (name: string, baseUrl: string, apiKey?: string, id?: string) =>
  post<EndpointCheck>('/hermes-api/api/providers/custom-endpoints/validate', {
    name,
    base_url: baseUrl,
    ...(apiKey ? { api_key: apiKey } : {}),
    // With no new key, the backend tests with the key already saved under this id.
    ...(id ? { id } : {})
  })

export const saveEndpoint = (payload: {
  id: string
  name: string
  base_url: string
  model: string
  models?: string[]
  api_key?: string
  make_default?: boolean
}) => post<{ ok?: boolean }>('/hermes-api/api/providers/custom-endpoints', payload)

export const deleteEndpoint = (id: string) =>
  harvisFetch<{ ok?: boolean }>(`/hermes-api/api/providers/custom-endpoints/${encodeURIComponent(id)}`, {
    method: 'DELETE'
  })

/** One machine in the k3s cluster, as GET /api/capabilities/hosting reports it. */
export interface HostingNode {
  name: string
  ready: boolean
  roles: string[]
  gpus: number
  cpu: string
  memory_gib: number
  version: string
}

/** Docker or Kubernetes, and what the installer set up (python_back_end/setup_flow.py). */
export interface HostingStatus {
  mode: 'docker' | 'kubernetes'
  detected_by: 'cluster' | 'default' | 'override'
  namespace: null | string
  nodes: HostingNode[]
  nodes_error: null | string
  gpu: { available: boolean; count: number }
  lan_models: { enabled: boolean; url: null | string }
  docker_socket: boolean
  commands: { enable: string; disable: string; status: string; join: string }
}

/** Backend route (not the Hermes gateway): nginx fronts `/api/` on the same origin. */
export const fetchHostingStatus = () => harvisFetch<HostingStatus>('/api/capabilities/hosting')

/** One pod of a Harvis service, as GET /api/capabilities/hosting/workloads reports it. */
export interface ClusterPod {
  name: string
  phase: string
  reason: null | string
  ready: boolean
  restarts: number
  last_restart: null | number
  node: string
  started: null | number
  containers: string[]
}

export interface ClusterService {
  name: string
  desired: number
  ready: number
  updated: number
  state: 'degraded' | 'down' | 'ready' | 'stopped'
  images: { name: string; tag: string }[]
  pods: ClusterPod[]
  restarts: number
}

export interface ClusterEvent {
  reason: string
  message: string
  object: string
  count: number
  last_seen: null | number
}

/** Admin-only, read-only view of the Harvis namespace (python_back_end/plugins/hosting/workloads.py). */
export interface ClusterWorkloads {
  mode: 'docker' | 'kubernetes'
  namespace: null | string
  services: ClusterService[]
  unmatched_pods: ClusterPod[]
  events: ClusterEvent[]
  error: null | string
  events_error?: string
}

export interface PodLogs {
  pod: string
  container: null | string
  previous: boolean
  lines: string[]
}

export const fetchClusterWorkloads = () => harvisFetch<ClusterWorkloads>('/api/capabilities/hosting/workloads')

export const fetchPodLogs = (pod: string, { container, previous }: { container?: string; previous?: boolean } = {}) => {
  const q = new URLSearchParams()

  if (container) {
    q.set('container', container)
  }

  if (previous) {
    q.set('previous', 'true')
  }

  const qs = q.toString()

  return harvisFetch<PodLogs>(`/api/capabilities/hosting/logs/${encodeURIComponent(pod)}${qs ? `?${qs}` : ''}`)
}

export const fetchMemory = () =>
  harvisFetch<{ entries: MemoryEntry[]; settings: LearnSettings; model: string }>('/hermes-api/api/harvis/memory')

export const addMemory = (content: string) => post<{ ok: boolean }>('/hermes-api/api/harvis/memory', { content })

export const keepMemory = (id: number) => post<{ ok: boolean }>(`/hermes-api/api/harvis/memory/${id}/keep`, {})

export const deleteMemory = (id: number) =>
  harvisFetch<{ ok: boolean }>(`/hermes-api/api/harvis/memory/${id}`, { method: 'DELETE' })

export const saveLearnSettings = (patch: Partial<LearnSettings>) =>
  post<LearnSettings>('/hermes-api/api/harvis/learn/settings', patch)

/** A messaging contact (Discord, Telegram …) paired to an account; it talks to Harvis as that account. */
export interface PairedContact {
  id: number
  platform: string
  identifier: string
  name: null | string
  enabled: boolean
  since: null | string
}

/** One account on this Harvis, as the admin's People page shows it. */
export interface Person {
  id: number
  name: string
  email: string
  joined: null | string
  is_admin: boolean
  blocked: boolean
  /** Chat messages per day; null = no limit, 0 = no chatting. */
  daily_message_limit: null | number
  /** Models on this server they may chat with; null = any. */
  allowed_models: null | string[]
  messages_today: number
  messages_week: number
  last_active: null | string
  chats: number
  paired: PairedContact[]
}

export type PersonControls = Partial<Pick<Person, 'allowed_models' | 'blocked' | 'daily_message_limit'>>

const PEOPLE = '/hermes-api/api/harvis/admin'

export const fetchPeople = () => harvisFetch<{ users: Person[] }>(`${PEOPLE}/users`)

export const updatePerson = (id: number, patch: PersonControls) =>
  harvisFetch<{ ok: boolean } & Required<PersonControls>>(`${PEOPLE}/users/${id}`, {
    method: 'PUT',
    body: JSON.stringify(patch)
  })

export const unpairContact = (id: number) =>
  harvisFetch<{ ok: boolean }>(`${PEOPLE}/senders/${id}`, { method: 'DELETE' })

export const fetchServerModels = () =>
  harvisFetch<{ models: { id: string; provider: string }[]; error?: string }>(`${PEOPLE}/models`)

export interface InstanceConfig {
  ENABLE_SIGNUP: boolean
  DEV_MODE: boolean
}

export const fetchInstanceConfig = () => harvisFetch<InstanceConfig>('/api/v1/auths/admin/config')

export const saveInstanceConfig = (patch: Partial<InstanceConfig>) =>
  post<InstanceConfig>('/api/v1/auths/admin/config', patch)

/** One model Ollama has pulled, as /api/cookbook/installed lists it (Ollama's /api/tags rows). */
export interface InstalledModel {
  name: string
  size?: number
  modified_at?: string
  /** Set by Ollama on models that run on ollama.com instead of this machine. */
  remote_host?: string
  details?: { family?: string; parameter_size?: string; quantization_level?: string }
}

/**
 * True for an Ollama model that runs on ollama.com: a `:cloud` tag, any tag ending `-cloud`, or a
 * row with `remote_host`. Same rule as the backend's `is_cloud_model`; Harvis is local-first, so
 * these never appear in the installed list.
 */
export function isCloudModel(m: Pick<InstalledModel, 'name' | 'remote_host'>): boolean {
  const name = (m.name ?? '').trim().toLowerCase()
  const tail = name.slice(name.lastIndexOf('/') + 1)

  if (tail.includes(':')) {
    const tag = name.slice(name.lastIndexOf(':') + 1)

    if (tag === 'cloud' || tag.endsWith('-cloud')) {
      return true
    }
  }

  return Boolean(m.remote_host)
}

/** One row of the cookbook's fit list (llmfit, ranked by the backend). */
export interface CookbookModel {
  name: string
  best_quant?: string
  downloadable?: boolean
  estimated_tps?: number
  fit_label?: string
  fit_level?: string
  memory_required_gb?: number
  ollama_tag?: string
  parameter_count?: string
  reason?: string
  serving?: string
}

const COOKBOOK = '/api/cookbook'

/** The machine models are pulled onto: the cookbook node with role "main", else the first one. */
export const fetchCookbookNode = () =>
  harvisFetch<{ nodes: { name: string; role?: string }[] }>(`${COOKBOOK}/nodes`).then(
    r => r.nodes?.find(n => n.role === 'main')?.name ?? r.nodes?.[0]?.name ?? 'main-host'
  )

export const fetchInstalledModels = (node: string) =>
  harvisFetch<{ models?: InstalledModel[]; error?: string }>(
    `${COOKBOOK}/installed?node=${encodeURIComponent(node)}`
  ).then(r => ({ ...r, models: (r.models ?? []).filter(m => !isCloudModel(m)) }))

/** The fit list: what runs well here first. `limit` keeps it short; the rest is a search away. */
export const fetchCookbookModels = async (node: string, search = ''): Promise<CookbookModel[]> => {
  const q = new URLSearchParams({ node, limit: '30' })
  const path = search.trim() ? `models?${q}&search=${encodeURIComponent(search.trim())}` : `recommend?${q}`
  const res = await harvisFetch<{ models?: CookbookModel[] } | CookbookModel[]>(`${COOKBOOK}/${path}`)

  return Array.isArray(res) ? res : (res.models ?? [])
}

export interface DownloadTarget {
  /** An Ollama tag ("gemma3:4b") or a Hugging Face repo with `quant`. */
  tag?: string
  repo?: string
  quant?: string
}

const sentence = (text: string) => (/[.!?]$/.test(text) ? text : `${text}.`)

/**
 * Pulls a model into Ollama and reports each progress event as it arrives. This is
 * a streaming POST, so it is fetch + ReadableStream rather than EventSource (which
 * cannot POST). Auth is the same cookie every other call here uses. Resolves when
 * the stream ends; rejects with a plain sentence on a refused request or an error
 * event. Aborting `signal` stops the read and the server drops the pull.
 */
export async function downloadModel(
  node: string,
  target: DownloadTarget,
  onEvent: (event: PullEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${COOKBOOK}/download`, {
    body: JSON.stringify({
      node,
      ...(target.tag ? { ollama_tag: target.tag } : { repo: target.repo, quant: target.quant })
    }),
    credentials: 'include',
    headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
    method: 'POST',
    signal
  })

  if (!res.ok || !res.body) {
    if (res.status === 401) {
      reportUnauthorized()
    }

    const body = (await res.json().catch(() => ({}))) as { detail?: unknown }

    throw new Error(typeof body.detail === 'string' ? body.detail : `The server answered ${res.status}.`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const parser = createSseParser()

  const handle = (events: PullEvent[]) => {
    for (const event of events) {
      if (event.error) {
        throw new Error(sentence(event.error))
      }

      onEvent(event)
    }
  }

  for (;;) {
    const { done, value } = await reader.read()

    if (done) {
      break
    }

    handle(parser.push(decoder.decode(value, { stream: true })))
  }

  handle(parser.push(decoder.decode()))
  handle(parser.flush())
}

export type ModelRequestStatus = 'approved' | 'denied' | 'open'

export interface ModelRequest {
  id: number
  model: string
  note: null | string
  status: ModelRequestStatus
  votes: number
  /** `username` is null when the account is gone, or for a viewer who may not see it. */
  requested_by: { id: null | number; username: null | string }
  created_at: string
  decided_at: null | string
  reason: null | string
}

/** 201 → a new request; 200 with `joined` → someone already asked, and this adds a vote. */
export const requestModel = (model: string, note?: string) =>
  post<{ request: ModelRequest; joined?: boolean }>('/api/model-requests', { model, ...(note ? { note } : {}) })

export const fetchMyRequests = () => harvisFetch<{ requests: ModelRequest[] }>('/api/model-requests/mine')

export const fetchOpenRequests = () => harvisFetch<{ requests: ModelRequest[] }>('/api/model-requests?status=open')

export const approveRequest = (id: number) => post<{ request: ModelRequest }>(`/api/model-requests/${id}/approve`, {})

export const denyRequest = (id: number, reason?: string) =>
  post<{ request: ModelRequest }>(`/api/model-requests/${id}/deny`, reason ? { reason } : {})

/** Another computer's Ollama, as /api/inference-nodes lists it. */
export interface InferenceNode {
  name: string
  label: string
  base_url: string
  /** "db" nodes were added in the app and can be removed here; the rest come from the server's setup. */
  source: string
  enabled: boolean
  reachable: boolean
  error: null | string
  models: string[]
}

export const fetchInferenceNodes = (force = false) =>
  harvisFetch<{ nodes: InferenceNode[] }>(`/api/inference-nodes${force ? '?force=true' : ''}`).then(r => r.nodes ?? [])

/** Trades the PIN the other computer is showing for a token; 400/403/409/429/502 come back as `detail`. */
export const pairInferenceNode = (address: string, pin: string, name?: string) =>
  post<{ node: InferenceNode }>('/api/inference-nodes/pair', { address, pin, ...(name ? { name } : {}) })

export const removeInferenceNode = (name: string) =>
  harvisFetch<{ deleted: boolean }>(`/api/inference-nodes/${encodeURIComponent(name)}`, { method: 'DELETE' })
