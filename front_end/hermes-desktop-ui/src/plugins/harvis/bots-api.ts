/**
 * Bots data layer — `/hermes-api/api/harvis/bots` (python_back_end/plugins/hermes_ui/bots.py).
 * A bot is a saved assistant: name, avatar, instructions, model, notebooks as
 * knowledge, starter prompts, and two tool switches. Starting a chat with one
 * goes over the gateway (`session.create` with `bot_id`), so the facade binds
 * the bot to the session before the first message.
 */

import { host } from '@hermes/plugin-sdk'

import { upsertOptimisticSession } from '@/app/session/hooks/use-session-actions/utils'
import { requestGatewayForAgent } from '@/store/gateway'
import { resolveNewChatOwnerRoute } from '@/store/profile'
import { setSessionOwnerHint } from '@/store/session'
import type { SessionCreateResponse } from '@/types/hermes'

import { harvisApi } from './api'

export interface BotAvatar {
  emoji?: string
  image?: string
}

export interface BotTools {
  web_research: boolean
  workspace_agent: boolean
}

export interface Bot {
  id: string
  handle: string
  name: string
  description: string
  instructions: string
  model: string
  avatar: BotAvatar
  notebook_ids: string[]
  starter_prompts: string[]
  tools: BotTools
  /** Reserved for a later "runs on" target; nothing sets it yet. */
  runs_on: Record<string, unknown>
  created_at: null | string
  updated_at: null | string
}

/** The editable half of a Bot (what create/update send). */
export type BotDraft = Pick<
  Bot,
  'avatar' | 'description' | 'instructions' | 'model' | 'name' | 'notebook_ids' | 'starter_prompts' | 'tools'
>

export const EMPTY_DRAFT: BotDraft = {
  name: '',
  description: '',
  instructions: '',
  model: '',
  avatar: { emoji: '🤖' },
  notebook_ids: [],
  starter_prompts: [],
  tools: { web_research: true, workspace_agent: true }
}

export const botsKey = ['harvis', 'bots'] as const
export const botForSessionKey = (sessionId: string) => ['harvis', 'bots', 'session', sessionId] as const

const BASE = '/hermes-api/api/harvis/bots'

export const fetchBots = () => harvisApi<{ bots: Bot[] }>(BASE).then(r => r.bots ?? [])

export const createBot = (draft: BotDraft) => harvisApi<Bot>(BASE, { method: 'POST', body: JSON.stringify(draft) })

export const updateBot = (id: string, draft: BotDraft) =>
  harvisApi<Bot>(`${BASE}/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(draft) })

export const deleteBot = (id: string) =>
  harvisApi<{ ok: boolean }>(`${BASE}/${encodeURIComponent(id)}`, { method: 'DELETE' })

export const duplicateBot = (id: string) =>
  harvisApi<Bot>(`${BASE}/${encodeURIComponent(id)}/duplicate`, { method: 'POST' })

/** The bot a chat speaks as, or null for a plain chat. */
export const fetchBotForSession = (sessionId: string) =>
  harvisApi<{ bot: Bot | null }>(`${BASE}/session/${encodeURIComponent(sessionId)}`).then(r => r.bot)

/** A new chat bound to the bot; the facade starts it on the bot's model. */
export async function startBotChat(botId: string): Promise<string> {
  // Mint it on the route a plain new chat would use and record its owner, or
  // every later prompt fails owner resolution.
  const route = resolveNewChatOwnerRoute()
  const params = { bot_id: botId }

  const res = route
    ? await requestGatewayForAgent<SessionCreateResponse>(route.connectionId, route.profile, 'session.create', params)
    : await host.request<SessionCreateResponse>('session.create', params)

  const sid = res.stored_session_id ?? res.session_id

  if (!sid) {
    throw new Error('the gateway returned no session id')
  }

  if (route && res.stored_session_id) {
    setSessionOwnerHint(res.stored_session_id, route)
  }

  // The sidebar row is the owner record for an unrouted create, exactly as
  // for a plain new chat; without it prompt.submit fails owner resolution.
  upsertOptimisticSession(res, sid, null, null, null, undefined, route)

  await host.openSession(sid, { intent: 'in-place' })

  return sid
}

export function draftOf(bot: Bot): BotDraft {
  return {
    name: bot.name,
    description: bot.description,
    instructions: bot.instructions,
    model: bot.model,
    avatar: { ...bot.avatar },
    notebook_ids: [...bot.notebook_ids],
    starter_prompts: [...bot.starter_prompts],
    tools: { ...bot.tools }
  }
}
