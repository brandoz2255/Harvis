import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { CopyButton } from '@/components/ui/copy-button'
import { AlertTriangle, CheckCircle2, Cpu, Globe, Info, Layers3, Network, Power, RefreshCw } from '@/lib/icons'
import { cn } from '@/lib/utils'

import { fetchHostingStatus, type HostingNode, type HostingStatus } from './harvis-api'
import { ListRow, ListRowSkeleton, Pill, SettingsContent, SettingsSection } from './primitives'

export const hostingKey = ['harvis', 'settings', 'hosting'] as const

const CAPTION =
  'text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-tertiary)'

function Bullets({ items }: { items: ReactNode[] }) {
  return (
    <ul className={cn('list-disc space-y-1.5 pl-5', CAPTION)}>
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  )
}

/** One installer command with its own copy button; the page cannot run it (see the Turn it on section). */
function CommandRow({ command, title }: { command: string; title: string }) {
  return (
    <ListRow
      action={<CopyButton appearance="inline" text={command} />}
      below={
        <code className="mt-1.5 block w-fit max-w-full rounded-md bg-(--ui-bg-quinary) px-2.5 py-1.5 font-mono text-[0.75rem] break-all text-foreground">
          {command}
        </code>
      }
      title={title}
    />
  )
}

function nodeSummary(node: HostingNode) {
  const parts = [
    `${node.gpus} GPU${node.gpus === 1 ? '' : 's'}`,
    `${node.cpu} CPU`,
    `${node.memory_gib} GiB memory`,
    node.roles.length ? node.roles.join(', ') : 'worker'
  ]

  return parts.join(' · ')
}

function NodeRows({ status }: { status: HostingStatus }) {
  if (status.nodes_error) {
    return (
      <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="min-w-0">
          <p className="font-medium">Could not list the machines in the cluster</p>
          <p className={cn('mt-0.5', CAPTION)}>{status.nodes_error}</p>
        </div>
      </div>
    )
  }

  if (!status.nodes.length) {
    return <p className={cn('mt-3', CAPTION)}>No machines reported yet.</p>
  }

  return (
    <div className="mt-2 divide-y">
      {status.nodes.map(node => (
        <ListRow
          description={nodeSummary(node)}
          hint={node.version}
          key={node.name}
          title={
            <span className="flex items-center gap-2">
              {node.name}
              {node.ready ? <Pill tone="primary">Ready</Pill> : <Pill tone="warn">Not ready</Pill>}
            </span>
          }
          wide
        />
      ))}
    </div>
  )
}

function StatusCard({ status }: { status: HostingStatus }) {
  const k8s = status.mode === 'kubernetes'
  const lanUrl = status.lan_models.enabled ? status.lan_models.url : null

  return (
    <div
      className={cn(
        'rounded-xl border px-4 py-3 text-sm',
        k8s ? 'border-primary/30 bg-primary/5 text-foreground' : 'border-border/70 bg-muted/20 text-foreground'
      )}
    >
      <div className="flex items-start gap-2">
        {k8s ? (
          <Layers3 className="mt-0.5 size-4 shrink-0 text-primary" />
        ) : (
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
        )}
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 font-medium">
            {k8s ? 'This Harvis runs on Kubernetes (k3s)' : 'This Harvis runs on Docker'}
            <Pill tone={k8s ? 'primary' : 'muted'}>{k8s ? 'Kubernetes' : 'Docker'}</Pill>
            {status.detected_by === 'override' && <Pill tone="warn">Set by HARVIS_HOSTING_MODE</Pill>}
          </p>
          <p className={cn('mt-1', CAPTION)}>
            {k8s
              ? `Namespace ${status.namespace ?? 'harvis'}. ${
                  status.nodes_error
                    ? 'GPU count unknown until the machines can be listed.'
                    : status.gpu.available
                      ? `${status.gpu.count} GPU${status.gpu.count === 1 ? '' : 's'} available to the cluster.`
                      : 'No GPU is visible to the cluster; models run on the CPU.'
                }`
              : status.gpu.available
                ? "Docker Compose with the NVIDIA runtime. Turn on Kubernetes hosting mode below to share this machine's models on your network."
                : "Docker Compose. Turn on Kubernetes hosting mode below to share this machine's models on your network."}
          </p>
        </div>
      </div>

      {k8s && (
        <>
          <NodeRows status={status} />
          {lanUrl ? (
            <ListRow
              action={<CopyButton appearance="inline" text={lanUrl} />}
              description="Other computers on your network can chat with this machine's models at this address. No account is needed."
              hint={lanUrl}
              title="Models address on your network"
              wide
            />
          ) : (
            <ListRow
              description="The models are not shared on the network: the installer skips this when HARVIS_LAN_MODELS_PORT=0, when Harvis uses a model server outside the cluster, or when ports 11434 and 11435 are both taken. Fix that and re-run the enable command below."
              title="Models address on your network"
              wide
            />
          )}
        </>
      )}
    </div>
  )
}

/**
 * Settings → Hosting: which way this Harvis is running (Docker Compose or a
 * small Kubernetes install), what the Kubernetes mode gives you, and the
 * installer commands that switch between the two. Read-only: switching needs
 * admin rights on the machine, so it happens in a terminal, not here.
 */
export function HostingSettings() {
  const hosting = useQuery({ queryFn: fetchHostingStatus, queryKey: hostingKey, refetchInterval: 30_000 })
  const status = hosting.data
  const commands = status?.commands

  return (
    <SettingsContent>
      <div className="mb-5">
        <div className="flex items-center gap-2 text-[length:var(--conversation-text-font-size)] font-medium">
          <Network className="size-4 text-muted-foreground" />
          Hosting
        </div>
        <p className={cn('mt-2 max-w-2xl', CAPTION)}>
          Harvis can run the normal way, with Docker on this machine, or in Kubernetes hosting mode, which lets other
          computers on your network use this machine's models. This page shows which one is running and explains the
          difference.
        </p>
      </div>

      {hosting.isLoading ? (
        <ListRowSkeleton wide />
      ) : hosting.error ? (
        <div className="flex items-start gap-2 rounded-xl border border-destructive/35 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <div className="min-w-0">
            <p className="font-medium">Could not read the hosting status</p>
            <p className="mt-1 text-xs opacity-80">{String((hosting.error as Error).message ?? hosting.error)}</p>
            <Button className="mt-2" onClick={() => void hosting.refetch()} size="sm" variant="textStrong">
              <RefreshCw className="size-3" /> Try again
            </Button>
          </div>
        </div>
      ) : status ? (
        <StatusCard status={status} />
      ) : null}

      <div className="mt-6">
        <SettingsSection icon={Info} title="What Kubernetes hosting mode is">
          <Bullets
            items={[
              'Harvis runs on a small Kubernetes install called k3s, on this same machine. Kubernetes is the system that big services use to keep many programs running together; k3s is the light version of it.',
              'You reach Harvis at the same address and port (9000) as before.',
              'Your chats, files and settings stay exactly where they are. Both modes use the same storage on this machine.'
            ]}
          />
        </SettingsSection>

        <SettingsSection icon={Globe} title="What you get">
          <Bullets
            items={[
              "Other computers on your network can use this machine's models. They do not need an account.",
              'That network address only allows chatting and listing models. Nobody can download, change or delete models through it.',
              'The models run in one Ollama inside the cluster. If this machine has an NVIDIA GPU, that Ollama gets it.',
              'More machines can join later with one command and show up in the list above. Harvis itself keeps running on this machine; joined machines do not add their GPUs yet.'
            ]}
          />
        </SettingsSection>

        <SettingsSection icon={Cpu} title="What you need">
          <Bullets
            items={[
              'Linux, with Docker installed.',
              'At least 8 GB of RAM. The Harvis images need about 7 GB of disk, plus room for the models you download.',
              'An NVIDIA GPU is optional. Without one, models run on the CPU, which is slower but works.',
              'Admin (sudo) rights on this machine, because installing k3s changes system services.'
            ]}
          />
        </SettingsSection>

        <SettingsSection icon={AlertTriangle} title="Things to know">
          <Bullets
            items={[
              "The terminal and Workspace runs still use this machine's Docker, with the same trust level as today.",
              'The models address has no password. Only turn it on when you are on a network you trust, such as your home or lab network.',
              'Optional features you have not enabled are not deployed, so the install stays as small as what you use.'
            ]}
          />
        </SettingsSection>

        <SettingsSection icon={Power} title="Turn it on or off">
          <p className={cn('mb-1', CAPTION)}>
            This page cannot switch modes by itself: installing Kubernetes needs admin rights on the machine. Open a
            terminal in the Harvis folder and run one of these. Turning it off goes straight back to Docker and keeps
            all your data.
          </p>
          {commands ? (
            <div className="divide-y">
              <CommandRow command={commands.enable} title="Turn on Kubernetes hosting mode" />
              <CommandRow command={commands.disable} title="Turn it off and go back to Docker" />
              <CommandRow command={commands.status} title="Check the status" />
              <CommandRow command={commands.join} title="Get the command another machine runs to join" />
            </div>
          ) : (
            <ListRowSkeleton wide />
          )}
        </SettingsSection>
      </div>
    </SettingsContent>
  )
}
