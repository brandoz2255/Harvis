/**
 * The bot's presence inside a chat: a strip above the composer naming the bot
 * the session speaks as, and the empty-transcript state with its starter
 * prompts. Both look the session up once and decline when it is a plain chat.
 */

import { Codicon, host, requestComposerInsert, Tip, useQuery, useValue } from '@hermes/plugin-sdk'

import { BotAvatar } from './bot-avatar'
import { botForSessionKey, fetchBotForSession } from './bots-api'

function useBotFor(sessionId: null | string) {
  return useQuery({
    enabled: Boolean(sessionId),
    queryFn: () => fetchBotForSession(sessionId ?? ''),
    queryKey: botForSessionKey(sessionId ?? ''),
    staleTime: 60_000
  })
}

/** COMPOSER_AREAS.top — the bot's name and face over the composer of its chats. */
export function BotChatHeader() {
  const sessionId = useValue(host.state.focusedStoredSessionId)
  const bot = useBotFor(sessionId)

  if (!sessionId || !bot.data) {
    return null
  }

  return (
    <div
      className="mb-1.5 flex items-center gap-2 rounded-lg border bg-(--ui-surface-raised,var(--background)) px-2.5 py-1.5"
      data-testid="harvis-bot-header"
    >
      <BotAvatar avatar={bot.data.avatar} name={bot.data.name} size="sm" />
      <span className="min-w-0 flex-1 truncate text-xs">
        <span className="font-medium">{bot.data.name}</span>
        {bot.data.description && <span className="text-(--ui-text-tertiary)"> — {bot.data.description}</span>}
      </span>
      <Tip label="Edit this bot">
        <button
          aria-label={`Edit ${bot.data.name}`}
          className="grid size-6 place-items-center rounded-sm text-(--ui-text-tertiary) hover:bg-accent/60 hover:text-foreground"
          onClick={() => host.navigate(`/bots?id=${encodeURIComponent(bot.data?.id ?? '')}`)}
          type="button"
        >
          <Codicon name="edit" size="0.8rem" />
        </button>
      </Tip>
    </div>
  )
}

/** CHAT_EMPTY_AREA — the blank transcript of a bot chat: face, name, starters. */
export function BotChatEmpty({ sessionId }: { sessionId: string }) {
  const bot = useBotFor(sessionId)

  if (!bot.data) {
    return null
  }

  return (
    <div
      className="mx-auto flex max-w-xl flex-col items-center gap-3 px-4 py-10 text-center"
      data-testid="harvis-bot-empty"
    >
      <BotAvatar avatar={bot.data.avatar} name={bot.data.name} size="lg" />
      <h2 className="text-lg font-semibold">{bot.data.name}</h2>
      {bot.data.description && <p className="text-sm text-(--ui-text-tertiary)">{bot.data.description}</p>}
      {bot.data.starter_prompts.length > 0 && (
        <div className="mt-2 flex flex-wrap justify-center gap-1.5">
          {bot.data.starter_prompts.map((prompt, i) => (
            <button
              className="rounded-full border px-3 py-1.5 text-left text-xs text-(--ui-text-secondary) hover:bg-accent/60 hover:text-foreground"
              key={i}
              onClick={() => requestComposerInsert(prompt)}
              type="button"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
