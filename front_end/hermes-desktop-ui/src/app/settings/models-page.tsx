import { useStore } from '@nanostores/react'
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { $session } from '@/lib/harvis-session'
import { Box, Cpu, Download, MessageQuestion, Monitor } from '@/lib/icons'
import { notify } from '@/store/notifications'

import { OtherComputers } from './add-computer'
import { fetchCookbookNode, fetchInstalledModels, type InstalledModel } from './harvis-api'
import { MyRequests, OpenRequests, RequestModelForm } from './model-requests'
import { DownloadProgress, GetModel, installedKey, useModelDownload } from './models-download'
import { formatBytes } from './pull-progress'
import { EmptyState, ListRow, ListRowSkeleton, SettingsContent, SettingsSection } from './primitives'

export function modelDetails(m: InstalledModel): string {
  return [m.details?.family, m.details?.parameter_size, m.details?.quantization_level].filter(Boolean).join(' · ')
}

function InstalledList({ error, loading, models }: { error?: string; loading: boolean; models: InstalledModel[] }) {
  if (loading) {
    return (
      <div className="grid gap-1">
        <ListRowSkeleton wide />
        <ListRowSkeleton wide />
      </div>
    )
  }

  if (error && models.length === 0) {
    return (
      <p className="py-2 text-[0.8125rem] text-destructive" role="alert">
        Could not read the installed models. {error}
      </p>
    )
  }

  if (models.length === 0) {
    return <EmptyState description="Models you download show up here." title="No models installed yet" />
  }

  return (
    <div className="divide-y">
      {models.map(m => (
        <ListRow
          action={
            typeof m.size === 'number' && m.size > 0 ? (
              <span className="text-[0.8125rem] text-(--ui-text-secondary) tabular-nums">{formatBytes(m.size)}</span>
            ) : undefined
          }
          description={modelDetails(m) || undefined}
          key={m.name}
          title={<span className="break-all">{m.name}</span>}
          wide
        />
      ))}
    </div>
  )
}

/**
 * Settings → Models. Everyone sees what is installed. Admins can download more and
 * answer requests; everyone else asks. The other-computers list is admin only.
 */
export function ModelsSettings() {
  const session = useStore($session)
  const isAdmin = session.status === 'signed-in' && session.user.role === 'admin'
  const node = useQuery({
    queryFn: fetchCookbookNode,
    queryKey: ['harvis', 'settings', 'models', 'node'],
    staleTime: 300_000
  })
  const nodeName = node.data

  const installed = useQuery({
    enabled: Boolean(nodeName),
    queryFn: () => fetchInstalledModels(nodeName as string),
    queryKey: installedKey(nodeName ?? ''),
    refetchOnWindowFocus: true
  })

  const { active, cancel, dismiss, start } = useModelDownload(nodeName)
  const models = installed.data?.models ?? []
  const names = useMemo(() => new Set(models.map(m => m.name)), [models])
  const busy = Boolean(active?.running)

  const download = (label: string, target: Parameters<typeof start>[1]) => {
    if (!nodeName) {
      notify({ kind: 'warning', title: 'No server to download onto', message: 'Reload the page and try again.' })
    } else if (!start(label, target)) {
      notify({ kind: 'info', title: 'A download is already running', message: 'Wait for it to finish or cancel it.' })
    }
  }

  const approved = (model: string) => {
    if (!nodeName) {
      notify({
        kind: 'warning',
        title: 'Approved, not downloaded',
        message: `Could not find the server to download onto. Get ${model} from Get a model.`
      })
    } else if (!start(model, { tag: model })) {
      notify({
        kind: 'info',
        title: 'Approved',
        message: `Another download is running. Get ${model} when it finishes.`
      })
    }
  }

  return (
    <SettingsContent>
      <SettingsSection
        icon={Box}
        meta={installed.data ? String(models.length) : undefined}
        title="Installed on this server"
      >
        {active && <DownloadProgress active={active} onCancel={cancel} onDismiss={dismiss} />}
        <InstalledList
          error={
            node.isError
              ? (node.error as Error).message
              : installed.isError
                ? (installed.error as Error).message
                : installed.data?.error
          }
          loading={node.isPending || (Boolean(nodeName) && installed.isPending)}
          models={models}
        />
      </SettingsSection>

      {isAdmin && nodeName && (
        <SettingsSection icon={Download} title="Get a model">
          <GetModel busy={busy} installed={names} node={nodeName} onDownload={download} />
        </SettingsSection>
      )}

      {isAdmin ? (
        <SettingsSection icon={MessageQuestion} title="Requests">
          <OpenRequests onApprove={approved} />
        </SettingsSection>
      ) : (
        <>
          <SettingsSection icon={MessageQuestion} title="Request a model">
            <RequestModelForm />
          </SettingsSection>
          <SettingsSection icon={Cpu} title="My requests">
            <MyRequests />
          </SettingsSection>
        </>
      )}

      {isAdmin && (
        <SettingsSection icon={Monitor} title="Other computers">
          <OtherComputers />
        </SettingsSection>
      )}
    </SettingsContent>
  )
}
