/**
 * Harvis backend calls the Settings pages make directly: provider status, coding
 * engine credentials, and learned memory. Same-origin cookie auth, like the rest
 * of the web build. Credentials are only ever sent, never read back.
 */

export async function harvisFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }
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

export const fetchMemory = () =>
  harvisFetch<{ entries: MemoryEntry[]; settings: LearnSettings; model: string }>('/hermes-api/api/harvis/memory')

export const addMemory = (content: string) => post<{ ok: boolean }>('/hermes-api/api/harvis/memory', { content })

export const deleteMemory = (id: number) =>
  harvisFetch<{ ok: boolean }>(`/hermes-api/api/harvis/memory/${id}`, { method: 'DELETE' })

export const saveLearnSettings = (patch: Partial<LearnSettings>) =>
  post<LearnSettings>('/hermes-api/api/harvis/learn/settings', patch)
