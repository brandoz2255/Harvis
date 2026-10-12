import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Activity, AlertTriangle, ChevronDown, ChevronRight, FileText, RefreshCw } from '@/lib/icons'
import { cn } from '@/lib/utils'

import {
  type ClusterPod,
  type ClusterService,
  type ClusterWorkloads,
  fetchClusterWorkloads,
  fetchPodLogs
} from './harvis-api'
import { ListRowSkeleton, Pill, SettingsSection } from './primitives'

export const clusterKey = ['harvis', 'settings', 'hosting', 'workloads'] as const

const CAPTION =
  'text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-tertiary)'

const STATE_LABEL: Record<ClusterService['state'], string> = {
  degraded: 'Struggling',
  down: 'Down',
  ready: 'Running',
  stopped: 'Turned off'
}

const STATE_TONE: Record<ClusterService['state'], 'muted' | 'primary' | 'warn'> = {
  degraded: 'warn',
  down: 'warn',
  ready: 'primary',
  stopped: 'muted'
}

export function ago(epochSeconds: null | number, now = Date.now()) {
  if (!epochSeconds) {
    return ''
  }

  const s = Math.max(0, Math.round(now / 1000 - epochSeconds))

  if (s < 60) {
    return `${s}s ago`
  }

  if (s < 3600) {
    return `${Math.round(s / 60)}m ago`
  }

  if (s < 86_400) {
    return `${Math.round(s / 3600)}h ago`
  }

  return `${Math.round(s / 86_400)}d ago`
}

function PodLogs({ pod }: { pod: ClusterPod }) {
  const [previous, setPrevious] = useState(false)
  const container = pod.containers.length > 1 ? pod.containers[0] : undefined

  const logs = useQuery({
    queryFn: () => fetchPodLogs(pod.name, { container, previous }),
    queryKey: [...clusterKey, 'logs', pod.name, container ?? '', previous],
    retry: false
  })

  return (
    <div className="mt-2 rounded-lg border border-border/70 bg-(--ui-bg-quinary)">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-3 py-1.5 text-xs">
        <span className="font-medium">
          {previous ? 'Before the last restart' : 'Latest'} log lines
          {container ? ` · ${container}` : ''}
        </span>
        <span className="text-muted-foreground">Passwords and tokens are hidden.</span>
        <span className="ml-auto flex gap-1">
          {pod.restarts > 0 && (
            <Button onClick={() => setPrevious(p => !p)} size="sm" variant="textStrong">
              {previous ? 'Show latest' : 'Show before restart'}
            </Button>
          )}
          <Button onClick={() => void logs.refetch()} size="sm" variant="textStrong">
            <RefreshCw className="size-3" /> Reload
          </Button>
        </span>
      </div>
      {logs.isLoading ? (
        <p className={cn('px-3 py-2', CAPTION)}>Reading logs…</p>
      ) : logs.error ? (
        <p className="px-3 py-2 text-xs text-destructive">{String((logs.error as Error).message ?? logs.error)}</p>
      ) : logs.data?.lines.length ? (
        <pre className="max-h-80 overflow-auto px-3 py-2 font-mono text-[0.7rem] leading-relaxed whitespace-pre-wrap break-all text-foreground">
          {logs.data.lines.join('\n')}
        </pre>
      ) : (
        <p className={cn('px-3 py-2', CAPTION)}>No log lines.</p>
      )}
    </div>
  )
}

function PodRow({ pod }: { pod: ClusterPod }) {
  const [open, setOpen] = useState(false)
  const trouble = !pod.ready || pod.reason

  return (
    <li className="py-1.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span className="font-mono text-foreground">{pod.name}</span>
        {trouble ? (
          <Pill tone="warn">{pod.reason ?? pod.phase}</Pill>
        ) : (
          <span className="text-muted-foreground">{pod.phase}</span>
        )}
        {pod.restarts > 0 && (
          <span className={pod.restarts >= 5 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}>
            {pod.restarts} restart{pod.restarts === 1 ? '' : 's'}
            {pod.last_restart ? `, last ${ago(pod.last_restart)}` : ''}
          </span>
        )}
        {pod.node && <span className="text-muted-foreground">on {pod.node}</span>}
        {pod.started && <span className="text-muted-foreground">up since {ago(pod.started)}</span>}
        <Button className="ml-auto" onClick={() => setOpen(o => !o)} size="sm" variant="textStrong">
          <FileText className="size-3" /> {open ? 'Hide logs' : 'Logs'}
        </Button>
      </div>
      {open && <PodLogs pod={pod} />}
    </li>
  )
}

function ServiceRow({ service }: { service: ClusterService }) {
  const [open, setOpen] = useState(service.state === 'down' || service.state === 'degraded')
  const tags = [...new Set(service.images.map(i => i.tag))].join(', ')

  return (
    <div className="py-2.5">
      <button
        aria-expanded={open}
        className="flex w-full items-center gap-2 text-left"
        onClick={() => setOpen(o => !o)}
        type="button"
      >
        {open ? (
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
        )}
        <span className="font-medium">{service.name}</span>
        <Pill tone={STATE_TONE[service.state]}>{STATE_LABEL[service.state]}</Pill>
        <span className={cn('ml-auto shrink-0', CAPTION)}>
          {service.ready}/{service.desired} ready
          {service.restarts > 0 ? ` · ${service.restarts} restarts` : ''}
          {tags ? ` · ${tags}` : ''}
        </span>
      </button>
      {open && (
        <div className="mt-1 pl-5.5">
          {service.pods.length ? (
            <ul className="divide-y divide-border/50">
              {service.pods.map(p => (
                <PodRow key={p.name} pod={p} />
              ))}
            </ul>
          ) : (
            <p className={CAPTION}>
              {service.state === 'stopped' ? 'Scaled to zero: nothing is running.' : 'No pods yet.'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function Summary({ data }: { data: ClusterWorkloads }) {
  const bad = data.services.filter(s => s.state === 'down' || s.state === 'degraded')

  if (!bad.length) {
    return (
      <p className={CAPTION}>
        All {data.services.filter(s => s.state === 'ready').length} running services are healthy in namespace{' '}
        {data.namespace}.
      </p>
    )
  }

  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
      <p>
        {bad.length === 1 ? '1 service needs' : `${bad.length} services need`} attention:{' '}
        {bad.map(s => s.name).join(', ')}. Open it below and check its logs.
      </p>
    </div>
  )
}

/**
 * Admin-only cluster panel on Settings → Hosting: every Harvis service in the
 * namespace, its pods and restarts, recent warnings, and a redacted log tail.
 * Read-only by design — the backend's service account cannot change anything,
 * so restarts and upgrades stay with the installer commands further down.
 */
export function ClusterPanel() {
  const workloads = useQuery({ queryFn: fetchClusterWorkloads, queryKey: clusterKey, refetchInterval: 15_000 })
  const data = workloads.data

  return (
    <SettingsSection icon={Activity} title="Services in the cluster">
      <div className="mb-2 flex items-center gap-2">
        <span className={CAPTION}>Only administrators see this. It refreshes every 15 seconds.</span>
        <Button
          className="ml-auto"
          disabled={workloads.isFetching}
          onClick={() => void workloads.refetch()}
          size="sm"
          variant="textStrong"
        >
          <RefreshCw className={cn('size-3', workloads.isFetching && 'animate-spin')} /> Refresh
        </Button>
      </div>

      {workloads.isLoading ? (
        <ListRowSkeleton wide />
      ) : workloads.error ? (
        <p className="text-sm text-destructive">
          Could not read the cluster: {String((workloads.error as Error).message ?? workloads.error)}
        </p>
      ) : data?.error ? (
        <p className="text-sm text-destructive">Could not read the cluster: {data.error}</p>
      ) : data ? (
        <>
          <Summary data={data} />
          <div className="mt-2 divide-y">
            {data.services.map(s => (
              <ServiceRow key={s.name} service={s} />
            ))}
          </div>
          {data.unmatched_pods.length > 0 && (
            <div className="mt-3">
              <p className="text-sm font-medium">Other pods (jobs and backups)</p>
              <ul className="divide-y divide-border/50">
                {data.unmatched_pods.map(p => (
                  <PodRow key={p.name} pod={p} />
                ))}
              </ul>
            </div>
          )}
          <div className="mt-4">
            <p className="text-sm font-medium">Recent warnings</p>
            {data.events_error ? (
              <p className={CAPTION}>Warnings are not available: {data.events_error}</p>
            ) : data.events.length ? (
              <ul className="mt-1 space-y-1.5">
                {data.events.map((e, i) => (
                  <li className="text-xs" key={`${e.object}-${e.reason}-${i}`}>
                    <span className="font-medium">{e.reason}</span>{' '}
                    <span className="font-mono text-muted-foreground">{e.object}</span>
                    {e.count > 1 && <span className="text-muted-foreground"> ×{e.count}</span>}
                    {e.last_seen && <span className="text-muted-foreground"> · {ago(e.last_seen)}</span>}
                    <div className="break-words text-(--ui-text-tertiary)">{e.message}</div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={CAPTION}>No recent warnings.</p>
            )}
          </div>
        </>
      ) : null}
    </SettingsSection>
  )
}
