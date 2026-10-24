import type {
  SkillHubPreview,
  SkillHubScanResult,
  SkillHubSearchResponse,
  SkillHubSourcesResponse,
  SkillInfo,
  StarmapGraph
} from '@/types/hermes'
import type { ActionResponse } from '@/types/hermes'

import { capabilityScoped, hermesApi, type ProfileScope, profileScoped } from './client'

export function getSkills(profile?: ProfileScope): Promise<SkillInfo[]> {
  return window.hermesDesktop.api<SkillInfo[]>({
    ...capabilityScoped(profile),
    path: '/api/skills'
  })
}

/** Raw SKILL.md text (frontmatter included) for ANY skill — bundled, hub, or
 *  learned — backing the Capabilities detail pane's full-skill view. */
export function getSkillContent(
  name: string,
  profile?: ProfileScope
): Promise<{ content: string; name: string; path: string }> {
  return window.hermesDesktop.api<{ content: string; name: string; path: string }>({
    ...capabilityScoped(profile),
    path: `/api/skills/content?name=${encodeURIComponent(name)}`
  })
}

export function setSkillEnabled(
  name: string,
  enabled: boolean,
  profile?: ProfileScope
): Promise<{ ok: boolean; name: string; enabled: boolean }> {
  return window.hermesDesktop.api<{ ok: boolean; name: string; enabled: boolean }>({
    ...capabilityScoped(profile),
    path: '/api/skills/toggle',
    method: 'PUT',
    body: { name, enabled }
  })
}

/** Add a skill the user wrote or uploaded (SKILL.md text). Saved on: adding it is the approval. */
export function createSkill(
  content: string,
  name?: string,
  profile?: ProfileScope
): Promise<{ message: string; name: string; ok: boolean }> {
  return window.hermesDesktop.api<{ message: string; name: string; ok: boolean }>({
    ...capabilityScoped(profile),
    path: '/api/skills',
    method: 'POST',
    body: { content, name: name || undefined }
  })
}

// ---------------------------------------------------------------------------
// Revisions a model proposed (python_back_end/plugins/hermes_ui/rest_skills.py).
// A proposal waits in `meta.pending` until a person approves it here; nothing a
// model writes changes a skill's text, switch or approval on its own.
// ---------------------------------------------------------------------------

export interface PendingSkillFile {
  /** Full proposed text; null when the proposal removes the file. */
  content: null | string
  /** Unified diff against the stored file ('' when unchanged). */
  diff: string
  path: string
  status: 'added' | 'changed' | 'removed' | 'unchanged'
}

export interface PendingSkill {
  at?: null | string
  /** Full proposed SKILL.md text. */
  content: string
  current_content: string
  current_description: string
  description: string
  /** Unified diff of the proposed text against the stored text. */
  diff: string
  enabled: boolean
  files: PendingSkillFile[]
  /** True when this proposal would create the skill (nothing stored yet). */
  is_new: boolean
  name: string
  /** Hash an approval must quote back; a proposal that changed since is refused. */
  pending_sha: string
  proposed_by?: null | string
  session_id?: null | string
  /** The stored skill changed after this proposal was written. */
  stale: boolean
}

export function getPending(profile?: ProfileScope): Promise<{ items: PendingSkill[] }> {
  return window.hermesDesktop.api<{ items: PendingSkill[] }>({
    ...capabilityScoped(profile),
    path: '/api/skills/pending'
  })
}

/** Approve the proposal the person reviewed. `pendingSha` (from getPending) makes the
 *  backend refuse a proposal that changed after it was opened, instead of approving it unseen. */
export function approvePending(
  name: string,
  pendingSha?: string,
  profile?: ProfileScope
): Promise<{ content_sha?: string; enabled?: boolean; message?: string; name: string; ok: boolean }> {
  return window.hermesDesktop.api<{
    content_sha?: string
    enabled?: boolean
    message?: string
    name: string
    ok: boolean
  }>({
    ...capabilityScoped(profile),
    path: '/api/skills/pending/approve',
    method: 'POST',
    body: { name, pending_sha: pendingSha || undefined }
  })
}

export function rejectPending(
  name: string,
  profile?: ProfileScope
): Promise<{ message?: string; name: string; ok: boolean; removed_row?: boolean }> {
  return window.hermesDesktop.api<{ message?: string; name: string; ok: boolean; removed_row?: boolean }>({
    ...capabilityScoped(profile),
    path: '/api/skills/pending/reject',
    method: 'POST',
    body: { name }
  })
}

export function getStarmapGraph(): Promise<StarmapGraph> {
  return hermesApi<StarmapGraph>({
    ...profileScoped(),
    // Backend REST contract — stays /api/learning even though the UI feature is
    // now "star map". Renaming this would break against an un-upgraded backend.
    path: '/api/learning/graph'
  })
}

export interface LearningNodeDetail {
  content: string
  kind: 'memory' | 'skill'
  label: string
  ok: boolean
}

export function getLearningNode(id: string, profile?: ProfileScope): Promise<LearningNodeDetail> {
  return window.hermesDesktop.api<LearningNodeDetail>({
    ...capabilityScoped(profile),
    path: `/api/learning/node?id=${encodeURIComponent(id)}`
  })
}

export function deleteLearningNode(id: string, profile?: ProfileScope): Promise<{ message: string; ok: boolean }> {
  return window.hermesDesktop.api<{ message: string; ok: boolean }>({
    ...capabilityScoped(profile),
    path: '/api/learning/node',
    method: 'DELETE',
    body: { id }
  })
}

export function editLearningNode(
  id: string,
  content: string,
  profile?: ProfileScope
): Promise<{ message: string; ok: boolean }> {
  return window.hermesDesktop.api<{ message: string; ok: boolean }>({
    ...capabilityScoped(profile),
    path: '/api/learning/node',
    method: 'PUT',
    body: { content, id }
  })
}

// ---------------------------------------------------------------------------
// Skills hub — search / preview / scan / install (parity with `hermes skills`
// and the dashboard's Browse-hub tab). Installs spawn background actions whose
// logs are tailed via getActionStatus().
// ---------------------------------------------------------------------------

const HUB_REQUEST_TIMEOUT_MS = 45_000

export function getSkillHubSources(profile?: null | string): Promise<SkillHubSourcesResponse> {
  return hermesApi<SkillHubSourcesResponse>({
    ...profileScoped(profile),
    path: '/api/skills/hub/sources',
    timeoutMs: HUB_REQUEST_TIMEOUT_MS
  })
}

export function searchSkillsHub(
  query: string,
  source = 'all',
  limit = 20,
  profile?: null | string
): Promise<SkillHubSearchResponse> {
  const params = new URLSearchParams({ q: query, source, limit: String(limit) })

  return hermesApi<SkillHubSearchResponse>({
    ...profileScoped(profile),
    path: `/api/skills/hub/search?${params.toString()}`,
    timeoutMs: HUB_REQUEST_TIMEOUT_MS
  })
}

export function previewSkillHub(identifier: string, profile?: null | string): Promise<SkillHubPreview> {
  return hermesApi<SkillHubPreview>({
    ...profileScoped(profile),
    path: `/api/skills/hub/preview?identifier=${encodeURIComponent(identifier)}`,
    timeoutMs: HUB_REQUEST_TIMEOUT_MS
  })
}

export function scanSkillHub(identifier: string, profile?: null | string): Promise<SkillHubScanResult> {
  return hermesApi<SkillHubScanResult>({
    ...profileScoped(profile),
    path: `/api/skills/hub/scan?identifier=${encodeURIComponent(identifier)}`,
    timeoutMs: HUB_REQUEST_TIMEOUT_MS
  })
}

export function installSkillFromHub(identifier: string, profile?: ProfileScope): Promise<ActionResponse> {
  return window.hermesDesktop.api<ActionResponse>({
    ...capabilityScoped(profile),
    path: '/api/skills/hub/install',
    method: 'POST',
    body: { identifier }
  })
}

export function uninstallSkillFromHub(name: string, profile?: ProfileScope): Promise<ActionResponse> {
  return window.hermesDesktop.api<ActionResponse>({
    ...capabilityScoped(profile),
    path: '/api/skills/hub/uninstall',
    method: 'POST',
    body: { name }
  })
}

export function updateSkillsFromHub(profile?: ProfileScope): Promise<ActionResponse> {
  return window.hermesDesktop.api<ActionResponse>({
    ...capabilityScoped(profile),
    path: '/api/skills/hub/update',
    method: 'POST',
    body: {}
  })
}
