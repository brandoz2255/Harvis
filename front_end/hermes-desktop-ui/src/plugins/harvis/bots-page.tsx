/**
 * Bots — the page at `/bots?id=<bot|new>`: the roster on the left, one bot's
 * form with a live preview on the right. The sidebar's "New bot" and edit
 * buttons deep-link here.
 */

import {
  Button,
  cn,
  Codicon,
  DetailColumn,
  EmptyState,
  ListColumn,
  MasterDetail,
  PageSearchShell,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'

import { BotAvatar } from './bot-avatar'
import { BotForm } from './bot-form'
import {
  type Bot,
  type BotDraft,
  botsKey,
  createBot,
  deleteBot,
  draftOf,
  duplicateBot,
  EMPTY_DRAFT,
  fetchBots,
  startBotChat,
  updateBot
} from './bots-api'

export function BotsPage() {
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const selected = params.get('id') ?? ''

  const bots = useQuery({ queryFn: fetchBots, queryKey: botsKey })
  const q = search.trim().toLowerCase()
  const rows = (bots.data ?? []).filter(
    b => !q || b.name.toLowerCase().includes(q) || b.description.toLowerCase().includes(q)
  )
  const select = (id: string) => setParams(id ? { id } : {}, { replace: true })
  const current = selected && selected !== 'new' ? (bots.data ?? []).find(b => b.id === selected) : undefined

  return (
    <PageSearchShell
      onSearchChange={setSearch}
      searchPlaceholder="Search bots"
      searchTrailingAction={
        <Button onClick={() => select('new')} size="sm">
          <Codicon name="add" size="0.8rem" /> New bot
        </Button>
      }
      searchValue={search}
    >
      <MasterDetail resizeId="harvis-bots-split" split="wide">
        <ListColumn>
          {bots.isLoading ? (
            <p className="px-2 text-xs text-(--ui-text-tertiary)">Loading…</p>
          ) : bots.error ? (
            <p className="px-2 text-xs text-destructive">{String(bots.error)}</p>
          ) : rows.length === 0 ? (
            <p className="px-2 text-xs text-(--ui-text-tertiary)">{q ? 'Nothing matches.' : 'No bots yet.'}</p>
          ) : (
            rows.map(bot => (
              <button
                className={cn(
                  'flex w-full items-center gap-2 rounded-md px-2 py-2 text-left hover:bg-accent/60',
                  selected === bot.id && 'bg-accent/70'
                )}
                key={bot.id}
                onClick={() => select(bot.id)}
                type="button"
              >
                <BotAvatar avatar={bot.avatar} name={bot.name} size="md" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{bot.name}</span>
                  <span className="block truncate text-xs text-(--ui-text-tertiary)">
                    {bot.description || bot.model || 'default model'}
                  </span>
                </span>
              </button>
            ))
          )}
        </ListColumn>
        <DetailColumn>
          <div className="p-4">
            {selected === 'new' ? (
              <BotEditor
                key="new"
                onSaved={bot => {
                  void queryClient.invalidateQueries({ queryKey: botsKey })
                  select(bot.id)
                }}
              />
            ) : current ? (
              <BotEditor
                bot={current}
                key={current.id}
                onDeleted={() => {
                  void queryClient.invalidateQueries({ queryKey: botsKey })
                  select('')
                }}
                onSaved={bot => {
                  void queryClient.invalidateQueries({ queryKey: botsKey })
                  select(bot.id)
                }}
              />
            ) : selected && !bots.isLoading ? (
              <EmptyState description="It may have been deleted." title="That bot is not here" />
            ) : (
              <EmptyState
                description="Pick a bot on the left to edit it, or make a new one. Click a bot in the sidebar to chat with it."
                title="Bots"
              />
            )}
          </div>
        </DetailColumn>
      </MasterDetail>
    </PageSearchShell>
  )
}

function BotEditor({ bot, onDeleted, onSaved }: { bot?: Bot; onDeleted?: () => void; onSaved: (bot: Bot) => void }) {
  const [draft, setDraft] = useState<BotDraft>(() => (bot ? draftOf(bot) : EMPTY_DRAFT))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState(false)

  // An edit elsewhere (duplicate, a refetch) refreshes the fields.
  useEffect(() => {
    if (bot) {
      setDraft(draftOf(bot))
    }
  }, [bot])

  const run = async (work: () => Promise<void>) => {
    setBusy(true)
    setError('')

    try {
      await work()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      {bot && (
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void run(() => startBotChat(bot.id).then(() => undefined))} size="sm">
            <Codicon name="comment-discussion" size="0.8rem" /> Chat with {bot.name}
          </Button>
        </div>
      )}
      <BotForm
        busy={busy}
        draft={draft}
        error={error}
        isNew={!bot}
        onChange={setDraft}
        onDelete={bot ? () => setConfirming(true) : undefined}
        onDuplicate={
          bot
            ? () =>
                void run(async () => {
                  const copy = await duplicateBot(bot.id)
                  onSaved(copy)
                })
            : undefined
        }
        onSave={() =>
          void run(async () => {
            const saved = bot ? await updateBot(bot.id, draft) : await createBot(draft)
            onSaved(saved)
          })
        }
      />
      {bot && confirming && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
          <span className="min-w-0 flex-1">Delete {bot.name}? Its chats stay; they just stop speaking as it.</span>
          <Button onClick={() => setConfirming(false)} size="sm" type="button" variant="outline">
            Keep
          </Button>
          <Button
            onClick={() =>
              void run(async () => {
                await deleteBot(bot.id)
                onDeleted?.()
              })
            }
            size="sm"
            type="button"
            variant="destructive"
          >
            Delete
          </Button>
        </div>
      )}
    </div>
  )
}
