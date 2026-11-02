import { useStore } from '@nanostores/react'
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { TitlebarIcon } from '@/app/shell/titlebar-icon'
import { PageLoader } from '@/components/page-loader'
import { Button } from '@/components/ui/button'
import { ErrorBanner } from '@/components/ui/error-state'
import { Tip } from '@/components/ui/tooltip'
import { $session } from '@/lib/harvis-session'
import { Box, Cpu, Download, Loader2, Plus } from '@/lib/icons'
import { notify, notifyError } from '@/store/notifications'

import { useRefreshHotkey } from '../hooks/use-refresh-hotkey'
import { PageSearchShell } from '../page-search-shell'
import {
  type CookbookNode,
  fetchCookbookNodes,
  fetchCookbookSystem,
  fetchInstalledModels,
  requestModel
} from '../settings/harvis-api'
import {
  DownloadProgress,
  FitList,
  installedKey,
  targetFor,
  useModelDownload,
  useSettledSearch
} from '../settings/models-download'
import { InstalledList } from '../settings/models-page'
import { SettingsSection } from '../settings/primitives'

import { AddNodeForm, NodeCard, nodesKey, systemKey } from './node-cards'

const errorText = (err: unknown) => (err instanceof Error && err.message ? err.message : undefined)

/** The honest state when `llmfit serve` does not answer: what the server said, and what to do about it. */
function LlmfitDown({
  admin,
  checking,
  node,
  onCheck
}: {
  admin: boolean
  checking: boolean
  node: CookbookNode
  onCheck: () => void
}) {
  return (
    <div className="grid max-w-[40rem] gap-2 rounded-md bg-(--ui-bg-tertiary)/50 p-4" role="status">
      <div className="text-[0.8125rem] font-medium">llmfit is not running on {node.name}</div>
      <p className="text-[0.8125rem] text-(--ui-text-secondary)">
        llmfit is the tool that reads this computer&apos;s hardware and works out which models fit. Without it there is
        no list to show.
      </p>
      {node.error && (
        <p className="break-words text-[0.75rem] text-(--ui-text-tertiary)">The server said: {node.error}</p>
      )}
      {!admin ? (
        <p className="text-[0.8125rem] text-(--ui-text-secondary)">Ask the admin to start it.</p>
      ) : node.role === 'main' ? (
        <p className="text-[0.8125rem] text-(--ui-text-secondary)">
          On the server it runs as the <code>llmfit</code> service in the Docker setup. Start that service, then check
          again.
        </p>
      ) : (
        <p className="text-[0.8125rem] text-(--ui-text-secondary)">
          On that computer, run <code>llmfit serve --host 0.0.0.0 --port 8787</code>, then check again. The server also
          has to be able to reach it over the network.
        </p>
      )}
      <div>
        <Button disabled={checking} onClick={onCheck} size="sm" variant="outline">
          {checking && <Loader2 className="animate-spin" />}
          Check again
        </Button>
      </div>
    </div>
  )
}

/** The selected computer's installed models and what fits it. Admins download; everyone else asks. */
function NodeModels({ admin, node, search }: { admin: boolean; node: string; search: string }) {
  const installed = useQuery({
    queryFn: () => fetchInstalledModels(node),
    queryKey: installedKey(node),
    refetchOnWindowFocus: true
  })

  const { active, cancel, dismiss, start } = useModelDownload(node)
  const [asked, setAsked] = useState<ReadonlySet<string>>(new Set())
  const [asking, setAsking] = useState<null | string>(null)
  const models = installed.data?.models ?? []
  const names = useMemo(() => new Set(models.map(m => m.name)), [models])
  const busy = Boolean(active?.running)

  const download = (label: string, target: Parameters<typeof start>[1]) => {
    if (!start(label, target)) {
      notify({ kind: 'info', title: 'A download is already running', message: 'Wait for it to finish or cancel it.' })
    }
  }

  const ask = async (tag: string) => {
    setAsking(tag)

    try {
      const { joined } = await requestModel(tag)
      setAsked(prev => new Set(prev).add(tag))
      notify({
        kind: 'success',
        title: 'Request sent',
        message: joined ? 'Someone already asked for that one. Your vote is added.' : 'The admin will see it.'
      })
    } catch (err) {
      notifyError(err, 'Could not send the request')
    } finally {
      setAsking(null)
    }
  }

  return (
    <>
      <SettingsSection
        icon={Box}
        meta={installed.data ? String(models.length) : undefined}
        title={`Installed on ${node}`}
      >
        {active && <DownloadProgress active={active} onCancel={cancel} onDismiss={dismiss} />}
        <InstalledList
          error={installed.isError ? errorText(installed.error) : installed.data?.error}
          loading={installed.isPending}
          models={models}
        />
      </SettingsSection>

      <SettingsSection icon={Download} title={search ? 'Matches' : 'What fits this computer'}>
        <FitList
          emptySearchText={
            admin
              ? 'Nothing matches that. Settings → Models can download an exact model name.'
              : 'Nothing matches that. You can ask for any model by name in Settings → Models.'
          }
          installed={names}
          node={node}
          renderAction={(m, { blocked, have, tag }) =>
            admin ? (
              <Button
                disabled={busy || have || blocked}
                onClick={() => download(tag, targetFor(m))}
                size="sm"
                variant="outline"
              >
                <Download />
                {have ? 'Installed' : 'Download'}
              </Button>
            ) : (
              // A request is for an Ollama name; a model without one has nothing the admin could pull.
              <span
                title={m.ollama_tag ? undefined : 'This one has no download name yet. Ask for it in Settings → Models.'}
              >
                <Button
                  disabled={have || blocked || !m.ollama_tag || asked.has(tag) || asking !== null}
                  onClick={() => void ask(tag)}
                  size="sm"
                  variant="outline"
                >
                  {have ? 'Installed' : asked.has(tag) ? 'Requested' : 'Request'}
                </Button>
              </span>
            )
          }
          search={search}
        />
        {admin && busy && (
          <p className="flex items-center gap-1.5 pt-2 text-[0.75rem] text-(--ui-text-tertiary)">
            <Loader2 className="size-3 animate-spin" />
            One download at a time. Wait for this one or cancel it.
          </p>
        )}
      </SettingsSection>
    </>
  )
}

/**
 * Every computer that can run models, its hardware, what is installed, and what fits. Admins
 * download and add or remove computers; everyone else can ask the admin for a model.
 */
export function CookbookView() {
  const queryClient = useQueryClient()
  const session = useStore($session)
  const admin = session.status === 'signed-in' && session.user.role === 'admin'
  const [text, setText] = useState('')
  const search = useSettledSearch(text)
  const [picked, setPicked] = useState<null | string>(null)
  const [adding, setAdding] = useState(false)
  const [checking, setChecking] = useState(false)

  const nodesQuery = useQuery({
    queryFn: fetchCookbookNodes,
    queryKey: nodesKey,
    refetchOnWindowFocus: true,
    staleTime: 15_000
  })

  const nodes = useMemo(() => nodesQuery.data ?? [], [nodesQuery.data])
  const selected = nodes.find(n => n.name === picked) ?? nodes.find(n => n.role === 'main') ?? nodes[0]

  const systems = useQueries({
    queries: nodes.map(n => ({
      enabled: n.alive,
      queryFn: () => fetchCookbookSystem(n.name),
      queryKey: systemKey(n.name),
      retry: false,
      staleTime: 300_000
    }))
  })

  const refresh = async () => {
    setChecking(true)

    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['harvis', 'cookbook'] }),
        queryClient.invalidateQueries({ queryKey: ['harvis', 'settings', 'models'] })
      ])
    } finally {
      setChecking(false)
    }
  }

  useRefreshHotkey(() => void refresh())

  return (
    <PageSearchShell
      onSearchChange={setText}
      searchHidden={!selected?.alive}
      searchPlaceholder="Search models"
      searchTrailingAction={
        <div className="flex items-center gap-1">
          {admin && (
            <Tip label="Add a computer">
              <Button
                aria-label="Add a computer"
                className="text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground"
                onClick={() => setAdding(a => !a)}
                size="icon-titlebar"
                variant="ghost"
              >
                <Plus className="size-3.5" />
              </Button>
            </Tip>
          )}
          <Tip label={checking ? 'Checking' : 'Check again'}>
            <Button
              aria-label="Check again"
              className="text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground"
              disabled={checking}
              onClick={() => void refresh()}
              size="icon-titlebar"
              variant="ghost"
            >
              <TitlebarIcon name={checking ? 'loading' : 'refresh'} spinning={checking} />
            </Button>
          </Tip>
        </div>
      }
      searchValue={text}
    >
      <div className="h-full overflow-y-auto px-3 pb-20 [scrollbar-gutter:stable]">
        {adding && admin && <AddNodeForm onAdded={setPicked} onClose={() => setAdding(false)} />}

        {nodesQuery.isPending ? (
          <PageLoader label="Looking for computers" />
        ) : nodesQuery.isError ? (
          <ErrorBanner>Could not load the list of computers. {errorText(nodesQuery.error)}</ErrorBanner>
        ) : !selected ? (
          <p className="py-6 text-center text-[0.8125rem] text-(--ui-text-secondary)">
            No computers are set up for models yet.{admin ? ' Add one with the plus button.' : ''}
          </p>
        ) : (
          <>
            <SettingsSection icon={Cpu} meta={String(nodes.length)} title="Computers">
              <div className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-2">
                {nodes.map((n, i) => (
                  <NodeCard
                    admin={admin}
                    key={n.name}
                    node={n}
                    onSelect={() => setPicked(n.name)}
                    selected={n.name === selected.name}
                    system={{
                      error: systems[i]?.isError ? errorText(systems[i].error) : undefined,
                      loading: Boolean(systems[i]?.isPending),
                      value: systems[i]?.data
                    }}
                  />
                ))}
              </div>
            </SettingsSection>

            {selected.alive ? (
              <NodeModels admin={admin} key={selected.name} node={selected.name} search={search} />
            ) : (
              <LlmfitDown admin={admin} checking={checking} node={selected} onCheck={() => void refresh()} />
            )}
          </>
        )}
      </div>
    </PageSearchShell>
  )
}
