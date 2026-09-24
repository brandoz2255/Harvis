/**
 * The Bots section of the sidebar, mounted next to Sessions through the
 * `sidebar.section` area. Click a bot to start a chat with it; "New bot" and
 * the row's edit button go to the /bots page.
 */

import { cn, Codicon, host, Tip, useQuery } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { BotAvatar } from './bot-avatar'
import { type Bot, botsKey, fetchBots, startBotChat } from './bots-api'

const INITIAL_VISIBLE = 5

export function BotsSidebarSection() {
  const [open, setOpen] = useState(true)
  const [showAll, setShowAll] = useState(false)
  const [starting, setStarting] = useState('')
  const [error, setError] = useState('')
  const bots = useQuery({ queryFn: fetchBots, queryKey: botsKey, staleTime: 30_000 })

  const list = bots.data ?? []
  const shown = showAll ? list : list.slice(0, INITIAL_VISIBLE)

  const start = async (bot: Bot) => {
    setStarting(bot.id)
    setError('')

    try {
      await startBotChat(bot.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setStarting('')
    }
  }

  return (
    <section className="shrink-0 pb-1" data-testid="harvis-bots-section">
      <div className="group/section flex shrink-0 items-center justify-between pb-1 pt-1.5 pr-1">
        <button
          aria-expanded={open}
          className="flex w-fit min-w-0 items-center gap-1 bg-transparent text-left leading-none"
          onClick={() => setOpen(v => !v)}
          type="button"
        >
          <span className="flex min-w-0 items-center gap-2 pl-2 text-[0.64rem] font-semibold tracking-[0.16em] text-(--theme-primary) uppercase">
            <span aria-hidden="true" className="dither inline-block size-2 shrink-0 rounded-[1px]" />
            <span className="min-w-0 truncate leading-none">Bots</span>
          </span>
          <Codicon
            className="text-(--ui-text-tertiary) opacity-0 transition group-hover/section:opacity-100"
            name={open ? 'chevron-down' : 'chevron-right'}
            size="0.7rem"
          />
        </button>
        <Tip label="New bot">
          <button
            aria-label="New bot"
            className="grid size-5 place-items-center rounded-sm text-(--ui-text-tertiary) hover:bg-(--ui-control-hover-background) hover:text-foreground"
            onClick={() => host.navigate('/bots?id=new')}
            type="button"
          >
            <Codicon name="add" size="0.75rem" />
          </button>
        </Tip>
      </div>
      {open && (
        <div className="flex flex-col gap-px pb-1">
          {bots.isLoading ? (
            <p className="px-2 py-1 text-[0.6875rem] text-(--ui-text-tertiary)">Loading…</p>
          ) : bots.error ? (
            <p className="px-2 py-1 text-[0.6875rem] text-destructive">{String(bots.error)}</p>
          ) : list.length === 0 ? (
            <button
              className="mx-1 rounded-md px-1.5 py-1.5 text-left text-[0.6875rem] text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground"
              onClick={() => host.navigate('/bots?id=new')}
              type="button"
            >
              No bots yet. Make one: a name, instructions, a model.
            </button>
          ) : (
            shown.map(bot => (
              <BotRow bot={bot} busy={starting === bot.id} key={bot.id} onStart={() => void start(bot)} />
            ))
          )}
          {!showAll && list.length > INITIAL_VISIBLE && (
            <button
              className="mx-1 rounded-md px-1.5 py-1 text-left text-[0.6875rem] text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground"
              onClick={() => setShowAll(true)}
              type="button"
            >
              Show {list.length - INITIAL_VISIBLE} more
            </button>
          )}
          {error && <p className="px-2 py-1 text-[0.6875rem] text-destructive">{error}</p>}
        </div>
      )}
    </section>
  )
}

function BotRow({ bot, busy, onStart }: { bot: Bot; busy: boolean; onStart: () => void }) {
  return (
    <div className="group/bot relative mx-1 flex items-center rounded-md hover:bg-(--chrome-action-hover)">
      <Tip label={bot.description || `Chat with ${bot.name}`}>
        <button
          aria-label={`Chat with ${bot.name}`}
          className={cn(
            'flex min-w-0 flex-1 items-center gap-2 px-1.5 py-1 text-left text-[0.8125rem] text-(--ui-text-secondary) group-hover/bot:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40',
            busy && 'cursor-wait opacity-60'
          )}
          disabled={busy}
          onClick={onStart}
          type="button"
        >
          <BotAvatar avatar={bot.avatar} name={bot.name} size="sm" />
          <span className="min-w-0 flex-1 truncate">{bot.name}</span>
        </button>
      </Tip>
      <Tip label="Edit bot">
        <button
          aria-label={`Edit ${bot.name}`}
          className="mr-1 hidden size-5 place-items-center rounded-sm text-(--ui-text-tertiary) group-hover/bot:grid hover:bg-(--ui-control-hover-background) hover:text-foreground"
          onClick={() => host.navigate(`/bots?id=${encodeURIComponent(bot.id)}`)}
          type="button"
        >
          <Codicon name="edit" size="0.75rem" />
        </button>
      </Tip>
    </div>
  )
}
