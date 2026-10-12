import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Download, Loader2, X } from '@/lib/icons'
import { notify } from '@/store/notifications'

import { type CookbookModel, downloadModel, type DownloadTarget, fetchCookbookModels } from './harvis-api'
import { createPullTracker, EMPTY_PULL, formatMeter, formatSpeed, type PullProgress } from './pull-progress'
import { ListRow, ListRowSkeleton, Pill } from './primitives'

export const installedKey = (node: string) => ['harvis', 'settings', 'models', 'installed', node] as const

export interface ActiveDownload {
  /** Plain-sentence failure, or the cancel notice; null while running or after success. */
  message: null | string
  model: string
  progress: PullProgress
  running: boolean
}

const isAbort = (err: unknown) => err instanceof DOMException && err.name === 'AbortError'

/**
 * One download at a time. `start` returns false when another is already running
 * (the caller says so); the installed list is refreshed once a pull succeeds.
 */
export function useModelDownload(node: string | undefined) {
  const queryClient = useQueryClient()
  const [active, setActive] = useState<ActiveDownload | null>(null)
  const abort = useRef<AbortController | null>(null)

  useEffect(() => () => abort.current?.abort(), [])

  const start = useCallback(
    (model: string, target: DownloadTarget): boolean => {
      if (!node || abort.current) {
        return false
      }

      const controller = new AbortController()
      const tracker = createPullTracker()
      let shownAt = 0
      abort.current = controller
      setActive({ message: null, model, progress: EMPTY_PULL, running: true })

      const finish = (message: null | string, progress: PullProgress) => {
        abort.current = null
        setActive({ message, model, progress, running: false })
      }

      void downloadModel(
        node,
        target,
        event => {
          const progress = tracker.apply(event)
          const now = Date.now()

          // Ollama can send hundreds of events a second; the bar does not need them all.
          if (now - shownAt > 100 || progress.done) {
            shownAt = now
            setActive({ message: null, model, progress, running: true })
          }
        },
        controller.signal
      )
        .then(() => {
          if (!tracker.value.done) {
            finish('The download stopped before it finished. Try again.', tracker.value)

            return
          }

          finish(null, tracker.value)
          notify({ kind: 'success', title: 'Model downloaded', message: model })
        })
        .catch((err: unknown) => {
          finish(
            isAbort(err)
              ? 'Download cancelled.'
              : err instanceof TypeError
                ? // fetch / stream failures surface as a bare TypeError ("network error", "Load failed").
                  'The connection to the server dropped. Try again.'
                : err instanceof Error
                  ? err.message
                  : 'The download failed.',
            tracker.value
          )
        })
        .finally(() => queryClient.invalidateQueries({ queryKey: installedKey(node) }))

      return true
    },
    [node, queryClient]
  )

  const cancel = useCallback(() => abort.current?.abort(), [])
  const dismiss = useCallback(() => setActive(a => (a?.running ? a : null)), [])

  return { active, cancel, dismiss, start }
}

export function DownloadProgress({
  active,
  onCancel,
  onDismiss
}: {
  active: ActiveDownload
  onCancel: () => void
  onDismiss: () => void
}) {
  const { message, model, progress, running } = active
  const known = progress.percent !== null
  const speed = formatSpeed(progress.speed)
  const finished = !running && !message

  return (
    <div className="mb-3 grid gap-2 rounded-md bg-(--ui-bg-tertiary)/50 p-3" data-testid="model-download">
      <div className="flex items-center gap-2 text-[0.8125rem]">
        <span className="min-w-0 flex-1 truncate font-medium">{model}</span>
        {running ? (
          <Button onClick={onCancel} size="sm" variant="outline">
            <X />
            Cancel
          </Button>
        ) : (
          <Button onClick={onDismiss} size="sm" variant="text">
            Dismiss
          </Button>
        )}
      </div>
      {(running || finished) && (
        <Progress
          aria-label={`Downloading ${model}`}
          animated
          indeterminate={running && !known}
          value={(progress.percent ?? (finished ? 100 : 0)) / 100}
        />
      )}
      {running && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.75rem] text-(--ui-text-secondary) tabular-nums">
          {known && <span>{progress.percent}%</span>}
          {progress.total > 0 && <span>{formatMeter(progress.completed, progress.total)}</span>}
          {speed && <span>{speed}</span>}
          <span className="text-(--ui-text-tertiary)">{progress.status || 'Starting'}</span>
        </div>
      )}
      {finished && <p className="text-[0.75rem] text-(--ui-text-secondary)">Downloaded. It is in the list above.</p>}
      {message && (
        <p className="text-[0.8125rem] text-destructive" role="alert">
          {message}
        </p>
      )}
    </div>
  )
}

const FIT_LABEL: Record<string, string> = {
  good: 'Fits',
  marginal: 'Tight fit',
  perfect: 'Fits easily',
  'too tight': 'Too big for this machine',
  too_tight: 'Too big for this machine',
  tight: 'Very tight fit'
}

function fitTone(level: string | undefined) {
  const l = (level ?? '').toLowerCase()

  return l === 'perfect' || l === 'good' ? 'primary' : l === 'marginal' ? 'muted' : 'warn'
}

/** What the person is told about a model before pulling it: how well it fits, and how big. */
export function fitHint(model: CookbookModel): string {
  return [
    model.parameter_count,
    model.best_quant,
    model.memory_required_gb ? `needs ${model.memory_required_gb.toFixed(1)} GB of memory` : ''
  ]
    .filter(Boolean)
    .join(' · ')
}

export function targetFor(model: CookbookModel): DownloadTarget {
  return model.ollama_tag ? { tag: model.ollama_tag } : { quant: model.best_quant, repo: model.name }
}

/** Admin only: pick from what fits this machine, or type any model name to pull. */
export function GetModel({
  busy,
  installed,
  node,
  onDownload
}: {
  busy: boolean
  installed: ReadonlySet<string>
  node: string
  onDownload: (label: string, target: DownloadTarget) => void
}) {
  const [text, setText] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    const id = window.setTimeout(() => setSearch(text.trim().length >= 2 ? text.trim() : ''), 350)

    return () => window.clearTimeout(id)
  }, [text])

  const list = useQuery({
    queryFn: () => fetchCookbookModels(node, search),
    queryKey: ['harvis', 'settings', 'models', 'cookbook', node, search],
    staleTime: 60_000
  })

  const name = text.trim()

  return (
    <div>
      <form
        className="mb-3 flex max-w-[40rem] gap-2"
        onSubmit={e => {
          e.preventDefault()

          if (name && !busy) {
            onDownload(name, { tag: name })
          }
        }}
      >
        <Input
          aria-label="Model name"
          onChange={e => setText(e.target.value)}
          placeholder="Search, or type a model name like gemma3:4b"
          value={text}
        />
        <Button disabled={!name || busy} type="submit">
          <Download />
          Download
        </Button>
      </form>

      {list.isPending ? (
        <div className="grid gap-1">
          <ListRowSkeleton wide />
          <ListRowSkeleton wide />
        </div>
      ) : list.isError ? (
        <p className="py-2 text-[0.8125rem] text-(--ui-text-secondary)" role="alert">
          {list.error instanceof Error
            ? `Could not load the list of models that fit this machine. ${list.error.message}`
            : 'Could not load the list of models that fit this machine.'}{' '}
          You can still type a model name above.
        </p>
      ) : (list.data ?? []).length === 0 ? (
        <p className="py-2 text-[0.8125rem] text-(--ui-text-secondary)">
          {search ? 'Nothing matches that. Press Download to try the exact name.' : 'No suggestions for this machine.'}
        </p>
      ) : (
        <div className="divide-y">
          {(list.data ?? []).map(m => {
            const tag = m.ollama_tag || m.name
            const have = installed.has(tag) || installed.has(`${tag}:latest`)
            const blocked = m.downloadable === false

            return (
              <ListRow
                action={
                  <Button
                    disabled={busy || have || blocked}
                    onClick={() => onDownload(tag, targetFor(m))}
                    size="sm"
                    variant="outline"
                  >
                    <Download />
                    {have ? 'Installed' : 'Download'}
                  </Button>
                }
                description={blocked ? (m.reason ?? 'Needs a GPU server, not this machine.') : fitHint(m)}
                key={m.name}
                title={
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="break-all">{m.name}</span>
                    {m.fit_level && !blocked && (
                      <Pill tone={fitTone(m.fit_level)}>{FIT_LABEL[m.fit_level.toLowerCase()] ?? m.fit_level}</Pill>
                    )}
                  </span>
                }
                wide
              />
            )
          })}
        </div>
      )}
      {busy && (
        <p className="flex items-center gap-1.5 pt-2 text-[0.75rem] text-(--ui-text-tertiary)">
          <Loader2 className="size-3 animate-spin" />
          One download at a time. Wait for this one or cancel it.
        </p>
      )}
    </div>
  )
}
