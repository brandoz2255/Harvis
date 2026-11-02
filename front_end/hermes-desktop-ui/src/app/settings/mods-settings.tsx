import { useStore } from '@nanostores/react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { AlertTriangle, Check, Loader2, Palette, Power, Trash2, Upload } from '@/lib/icons'
import { modsApi } from '@/mods/api'
import { parseModPackage } from '@/mods/package'
import { $islandVisible, $mods, groupByName, type ModGroup } from '@/mods/store'
import type { ModCard, ModRow, ModStatus } from '@/mods/types'
import { confirm } from '@/store/confirm'
import { notify, notifyError } from '@/store/notifications'

import { EmptyState, ListRow, ListRowSkeleton, Pill, SettingsContent, SettingsSection, ToggleRow } from './primitives'

const modsKey = ['harvis', 'settings', 'mods'] as const

const STATUS_LABEL: Record<ModStatus, string> = { broken: 'Broken', draft: 'Waiting for approval', off: 'Off', on: 'On' }
const STATUS_TONE: Record<ModStatus, 'muted' | 'primary' | 'warn'> = {
  broken: 'warn',
  draft: 'muted',
  off: 'muted',
  on: 'primary'
}

const CSP_LABELS: [keyof NonNullable<ModCard['csp']>, string][] = [
  ['connectDomains', 'Can talk to'],
  ['resourceDomains', 'Can load scripts, images and fonts from'],
  ['frameDomains', 'Can embed'],
  ['baseUriDomains', 'Can set its base address to']
]

function AssistantLabel() {
  return <Pill tone="warn">Drafted by the assistant</Pill>
}

/** Everything the server put on the Card, shown in full. Approve sends THIS card's hash. */
function ApprovalCard({
  busy,
  card,
  onApprove,
  onCancel,
  row
}: {
  busy: boolean
  card: ModCard
  onApprove: () => void
  onCancel: () => void
  row: ModRow
}) {
  const looks = Object.entries(card.looks ?? {})

  return (
    <div className="mt-3 grid max-w-[40rem] gap-3 rounded-md bg-(--ui-bg-tertiary)/50 p-3 text-[0.8125rem]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">
          {card.name} {card.version}
        </span>
        {card.tiers.map(tier => (
          <Pill key={tier}>{tier}</Pill>
        ))}
        {row.source === 'agent' && <AssistantLabel />}
      </div>
      {card.author && <div className="text-(--ui-text-secondary)">By {card.author}</div>}
      {card.description && <div className="text-(--ui-text-secondary)">{card.description}</div>}

      <div>
        <div className="text-[0.75rem] text-(--ui-text-tertiary)">Version fingerprint (what you are approving)</div>
        <code className="block break-all font-mono text-[0.72rem]">{card.hash}</code>
      </div>

      <div>
        <div className="text-[0.75rem] text-(--ui-text-tertiary)">Where it shows</div>
        <div>{card.slot ?? 'Nowhere (no screen of its own)'}</div>
      </div>

      {card.slot && (
        <div className="grid gap-1.5">
          <div className="text-[0.75rem] text-(--ui-text-tertiary)">Network access</div>
          {card.csp && CSP_LABELS.some(([key]) => card.csp?.[key]?.length) ? (
            CSP_LABELS.filter(([key]) => card.csp?.[key]?.length).map(([key, label]) => (
              <div key={key}>
                <span className="text-(--ui-text-secondary)">{label}: </span>
                <span className="break-all font-mono text-[0.72rem]">{card.csp?.[key].join(', ')}</span>
              </div>
            ))
          ) : (
            <div>None. It cannot fetch or load anything, though it could still open a web page carrying what it shows.</div>
          )}
        </div>
      )}

      {card.permissions.length > 0 && (
        <div>
          <div className="text-[0.75rem] text-(--ui-text-tertiary)">Permissions</div>
          <div>{card.permissions.join(', ')}</div>
        </div>
      )}

      {card.hooks.length > 0 && (
        <div className="grid gap-1">
          <div className="text-[0.75rem] text-(--ui-text-tertiary)">Rules it adds ({card.hooks.length})</div>
          {card.hooks.map((hook, i) => (
            <code className="block break-all rounded bg-(--ui-bg-quaternary) px-2 py-1 font-mono text-[0.72rem]" key={i}>
              {JSON.stringify(hook)}
            </code>
          ))}
        </div>
      )}

      {looks.length > 0 && (
        <div className="grid gap-1">
          <div className="text-[0.75rem] text-(--ui-text-tertiary)">Looks it changes</div>
          {looks.map(([key, value]) => (
            <div className="font-mono text-[0.72rem]" key={key}>
              {key}: {String(value)}
            </div>
          ))}
        </div>
      )}

      {card.warnings.length > 0 && (
        <ul className="grid gap-1 text-amber-600 dark:text-amber-300">
          {card.warnings.map(warning => (
            <li className="flex gap-1.5" key={warning}>
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <span>{warning}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        <Button disabled={busy} onClick={onApprove} size="sm">
          {busy ? <Loader2 className="animate-spin" /> : <Check />}
          Approve and turn on
        </Button>
        <Button disabled={busy} onClick={onCancel} size="sm" variant="outline">
          Cancel
        </Button>
      </div>
    </div>
  )
}

interface Review {
  card: ModCard
  row: ModRow
}

function InstallBox({ onReview }: { onReview: (review: Review) => void }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const readFile = async (file: File | undefined) => {
    if (file) {
      setText(await file.text())
    }
  }

  const install = async () => {
    setBusy(true)

    try {
      const { approval, mod } = await modsApi.install(parseModPackage(text))
      onReview({ card: approval, row: mod })
      setText('')
    } catch (err) {
      notifyError(err, 'Could not read that mod')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid max-w-[40rem] gap-2 py-2">
      <Textarea
        className="min-h-28 font-mono text-[0.72rem]"
        onChange={e => setText(e.target.value)}
        placeholder='{"manifest": {...}, "resources": {...}}'
        value={text}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={busy || !text.trim()} onClick={() => void install()} size="sm">
          {busy ? <Loader2 className="animate-spin" /> : null}
          Review
        </Button>
        <Button onClick={() => fileRef.current?.click()} size="sm" variant="outline">
          <Upload />
          Choose a .json file
        </Button>
        <input
          accept=".json,application/json"
          className="hidden"
          onChange={e => {
            void readFile(e.target.files?.[0])
            e.target.value = ''
          }}
          ref={fileRef}
          type="file"
        />
        <span className="text-[0.75rem] text-(--ui-text-tertiary)">
          Nothing runs until you read the card and approve it.
        </span>
      </div>
    </div>
  )
}

function ModItem({
  group,
  onChanged,
  onReview,
  review
}: {
  group: ModGroup
  onChanged: () => Promise<unknown>
  onReview: (review: Review | null, row?: ModRow) => void
  review: Review | null
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const { head, name, pending } = group
  const reviewing = review && review.row.name === name

  const run = async (label: string, fn: () => Promise<unknown>, failure: string) => {
    setBusy(label)

    try {
      await fn()
      await onChanged()
    } catch (err) {
      notifyError(err, failure)
    } finally {
      setBusy(null)
    }
  }

  // The server builds the card from the bytes it stored for this exact hash.
  const openCard = (row: ModRow) =>
    run(
      'review',
      async () => {
        const { approval, mod } = await modsApi.card(row.name, row.hash)
        onReview({ card: approval, row: mod })
      },
      'Could not open the approval card'
    )

  const remove = async () => {
    const ok = await confirm({
      title: `Remove ${name}?`,
      description: 'It stops running and every saved version of it is deleted.',
      confirmLabel: 'Remove',
      destructive: true
    })

    if (ok) {
      await run('remove', () => modsApi.remove(name), 'Could not remove it')
    }
  }

  return (
    <ListRow
      action={
        <div className="flex flex-wrap items-center gap-2 @2xl:justify-end">
          {head.status === 'on' ? (
            <Button
              disabled={busy !== null}
              onClick={() => void run('disable', () => modsApi.disable(name), 'Could not turn it off')}
              size="sm"
              variant="outline"
            >
              {busy === 'disable' ? <Loader2 className="animate-spin" /> : <Power />}
              Turn off
            </Button>
          ) : (
            <Button disabled={busy !== null} onClick={() => void openCard(head)} size="sm">
              {busy === 'review' ? <Loader2 className="animate-spin" /> : null}
              Review
            </Button>
          )}
          <Button
            disabled={busy !== null}
            onClick={() => void run('rollback', () => modsApi.rollback(name), 'Nothing to roll back to')}
            size="sm"
            variant="outline"
          >
            Roll back
          </Button>
          <Button disabled={busy !== null} onClick={() => void remove()} size="sm" variant="outline">
            <Trash2 />
            Remove
          </Button>
        </div>
      }
      below={
        <>
          {head.status_reason && head.status !== 'on' && (
            <p className="mt-1.5 text-[0.75rem] text-amber-600 dark:text-amber-300">{head.status_reason}</p>
          )}
          {pending.map(row => (
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[0.75rem] text-(--ui-text-secondary)" key={row.hash}>
              <span>Newer version {row.version} is waiting for approval.</span>
              {row.source === 'agent' && <AssistantLabel />}
              <Button disabled={busy !== null} onClick={() => void openCard(row)} size="inline" variant="text">
                Review
              </Button>
            </div>
          ))}
          {reviewing && (
            <ApprovalCard
              busy={busy === 'approve'}
              card={review.card}
              onApprove={() =>
                void run(
                  'approve',
                  async () => {
                    await modsApi.approve(name, review.card.hash)
                    onReview(null)
                    notify({ kind: 'success', title: 'Turned on', message: name })
                  },
                  'Could not approve it'
                )
              }
              onCancel={() => onReview(null)}
              row={review.row}
            />
          )}
        </>
      }
      description={head.manifest.description}
      title={
        <span className="flex flex-wrap items-center gap-2">
          {name}
          <span className="font-normal text-(--ui-text-tertiary)">{head.version}</span>
          <Pill tone={STATUS_TONE[head.status]}>{STATUS_LABEL[head.status]}</Pill>
          {head.source === 'agent' && <AssistantLabel />}
        </span>
      }
    />
  )
}

/** Per-person mods: install from a package, read the approval card, turn on or off. */
export function ModsSettings() {
  const queryClient = useQueryClient()
  const islandVisible = useStore($islandVisible)
  const [review, setReview] = useState<Review | null>(null)

  const mods = useQuery({
    queryFn: async () => {
      const rows = await modsApi.list()
      $mods.set(rows)

      return rows
    },
    queryKey: modsKey,
    refetchOnWindowFocus: true
  })

  const groups = groupByName(mods.data ?? [])
  const refresh = () => queryClient.invalidateQueries({ queryKey: modsKey })

  // A card for a mod that is not in the list yet (just installed) is shown in its own block below the form.
  const listed = review ? groups.some(group => group.name === review.row.name) : false

  return (
    <SettingsContent>
      <SettingsSection icon={Palette} title="Island">
        <ToggleRow
          checked={islandVisible}
          description="A small pixel town behind a fresh chat where your bots walk around; Explore opens it fullscreen. It slows down while a run is busy and stops when you cannot see it. You can draw it with your own game files from Explore — they never leave this browser."
          label="Show the island"
          onChange={on => $islandVisible.set(on)}
        />
      </SettingsSection>

      <SettingsSection icon={Upload} title="Install a mod">
        <InstallBox
          onReview={next => {
            setReview(next)
            void refresh()
          }}
        />
        {review && !listed && (
          <ApprovalCard
            busy={false}
            card={review.card}
            onApprove={() =>
              void modsApi
                .approve(review.row.name, review.card.hash)
                .then(() => {
                  setReview(null)
                  notify({ kind: 'success', title: 'Turned on', message: review.row.name })

                  return refresh()
                })
                .catch(err => notifyError(err, 'Could not approve it'))
            }
            onCancel={() => setReview(null)}
            row={review.row}
          />
        )}
      </SettingsSection>

      <SettingsSection icon={Palette} meta={mods.data ? String(groups.length) : undefined} title="Your mods">
        {mods.isPending ? (
          <div className="grid gap-1">
            <ListRowSkeleton />
            <ListRowSkeleton />
          </div>
        ) : mods.isError ? (
          <p className="py-3 text-[0.8125rem] text-destructive" role="alert">
            {mods.error instanceof Error ? mods.error.message : 'Could not load your mods.'}
          </p>
        ) : groups.length === 0 ? (
          <EmptyState title="No mods yet" />
        ) : (
          <div className="divide-y">
            {groups.map(group => (
              <ModItem
                group={group}
                key={group.name}
                onChanged={refresh}
                onReview={next => setReview(next)}
                review={review}
              />
            ))}
          </div>
        )}
      </SettingsSection>
    </SettingsContent>
  )
}
