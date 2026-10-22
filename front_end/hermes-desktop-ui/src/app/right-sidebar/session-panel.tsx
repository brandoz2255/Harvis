import { useStore } from '@nanostores/react'
import { type ReactNode, useMemo } from 'react'

import { useGatewayRequest } from '@/app/gateway/hooks/use-gateway-request'
import { useContextBreakdown } from '@/app/shell/hooks/use-context-breakdown'
import { Codicon } from '@/components/ui/codicon'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { compactNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  $activeSessionId,
  $busy,
  $currentCwd,
  $currentModel,
  $currentProvider,
  $currentUsage,
  $messages,
  $selectedStoredSessionId,
  $workspaceCwdOwner
} from '@/store/session'

import { SidebarPanelLabel } from '../shell/sidebar-label'

import { sessionChangedFiles } from './session-changes'
import { $sessionPanelCollapsed, setSessionPanelCollapsed } from './store'

const MAX_CHANGES = 8

interface SessionPanelProps {
  onActivateFile: (path: string) => void
}

// "…/chat-7/workspace": the last two segments say which sandbox this is; the
// full path rides on the tooltip.
function shortFolder(cwd: string): string {
  const parts = cwd.split(/[\\/]+/).filter(Boolean)

  return parts.length > 2 ? `…/${parts.slice(-2).join('/')}` : cwd
}

export function SessionPanel({ onActivateFile }: SessionPanelProps) {
  const { t } = useI18n()
  const r = t.rightSidebar
  const collapsed = useStore($sessionPanelCollapsed)
  const model = useStore($currentModel).trim()
  const provider = useStore($currentProvider).trim()
  const usage = useStore($currentUsage)
  const messages = useStore($messages)
  const busy = useStore($busy)
  const activeSessionId = useStore($activeSessionId)
  const currentCwd = useStore($currentCwd).trim()
  const selectedStoredSessionId = useStore($selectedStoredSessionId)
  const workspaceCwdOwner = useStore($workspaceCwdOwner)
  const { requestGateway } = useGatewayRequest()

  // Same ownership rule as the file tree: a retained cwd from the previous
  // conversation is not this session's folder.
  const cwd = currentCwd && (workspaceCwdOwner ?? null) === (selectedStoredSessionId ?? null) ? currentCwd : ''

  // The statusbar gauge's own source: a measured figure once a turn has run,
  // an estimate before that (a resumed chat has no measured figure yet).
  const { breakdown } = useContextBreakdown({ busy, enabled: !collapsed, requestGateway, sessionId: activeSessionId })
  const contextMax = breakdown?.context_max ?? usage.context_max ?? 0
  const contextUsed = breakdown?.context_used ?? usage.context_used ?? 0
  const contextPercent = Math.max(
    0,
    Math.min(100, Math.round(breakdown?.context_percent ?? usage.context_percent ?? 0))
  )

  const changes = useMemo(() => (collapsed ? [] : sessionChangedFiles(messages, cwd)), [collapsed, cwd, messages])
  const shown = changes.slice(0, MAX_CHANGES)

  const modelLabel = model ? (provider ? `${model} · ${provider}` : model) : r.sessionModelNone

  return (
    <section
      aria-label={r.sessionTitle}
      className="flex shrink-0 flex-col border-b border-(--ui-stroke-secondary) pb-1.5"
      data-slot="session-panel"
    >
      <button
        aria-expanded={!collapsed}
        aria-label={collapsed ? r.sessionExpand : r.sessionCollapse}
        className="group/session-header flex h-7 shrink-0 items-center gap-1 px-2.5 text-left outline-none focus-visible:bg-(--ui-bg-elevated)"
        onClick={() => setSessionPanelCollapsed(!collapsed)}
        type="button"
      >
        <Codicon
          className="text-(--ui-text-quaternary) group-hover/session-header:text-(--ui-text-secondary)"
          name={collapsed ? 'chevron-right' : 'chevron-down'}
          size="0.8125rem"
        />
        <SidebarPanelLabel className="pl-1">{r.sessionTitle}</SidebarPanelLabel>
      </button>

      {!collapsed && (
        <dl className="m-0 flex flex-col gap-2 px-3.5 pt-0.5 text-[0.7rem] leading-snug">
          <Row label={r.sessionRunsOn}>
            <Tip label={modelLabel}>
              <span
                className={cn('block truncate', model ? 'text-(--ui-text-secondary)' : 'text-(--ui-text-quaternary)')}
                data-slot="session-model"
              >
                {modelLabel}
              </span>
            </Tip>
          </Row>

          <Row label={r.sessionFolder}>
            {cwd ? (
              <Tip label={cwd}>
                <span className="block truncate font-mono text-(--ui-text-secondary)" data-slot="session-folder">
                  {shortFolder(cwd)}
                </span>
              </Tip>
            ) : (
              <span className="block truncate text-(--ui-text-quaternary)">{r.sessionFolderNone}</span>
            )}
          </Row>

          <Row label={r.sessionContext}>
            {contextMax > 0 ? (
              <div className="flex flex-col gap-1" data-slot="session-context">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-(--ui-text-secondary)">{r.sessionContextPercent(contextPercent)}</span>
                  <span className="truncate text-(--ui-text-quaternary)">
                    {r.sessionContextTokens(`~${compactNumber(contextUsed)}`, compactNumber(contextMax))}
                  </span>
                </div>
                <div
                  aria-label={r.sessionContext}
                  aria-valuemax={100}
                  aria-valuemin={0}
                  aria-valuenow={contextPercent}
                  className="h-1 overflow-hidden rounded-full bg-(--ui-stroke-tertiary)"
                  role="progressbar"
                >
                  <div className="h-full rounded-full bg-(--theme-primary)" style={{ width: `${contextPercent}%` }} />
                </div>
              </div>
            ) : (
              <span className="block text-(--ui-text-quaternary)">{r.sessionContextUnknown}</span>
            )}
          </Row>

          <Row label={r.sessionChanges}>
            {shown.length === 0 ? (
              <span className="block text-(--ui-text-quaternary)">{r.sessionNoChanges}</span>
            ) : (
              <ul className="m-0 flex list-none flex-col p-0" data-slot="session-changes">
                {shown.map(file => (
                  <li className="min-w-0" key={file.path}>
                    <Tip label={file.path}>
                      <button
                        aria-label={r.sessionOpenFile(file.label)}
                        className="flex w-full min-w-0 items-center gap-1.5 rounded-sm py-0.5 text-left text-(--ui-text-secondary) outline-none hover:bg-(--ui-bg-elevated) hover:text-(--ui-text-primary) focus-visible:bg-(--ui-bg-elevated)"
                        onClick={() => onActivateFile(file.path)}
                        type="button"
                      >
                        <Codicon className="shrink-0 text-(--ui-text-quaternary)" name="file" size="0.75rem" />
                        <span className="min-w-0 truncate">{file.label}</span>
                      </button>
                    </Tip>
                  </li>
                ))}
                {changes.length > shown.length && (
                  <li className="pt-0.5 text-(--ui-text-quaternary)">
                    {r.sessionMoreChanges(changes.length - shown.length)}
                  </li>
                )}
              </ul>
            )}
          </Row>
        </dl>
      )}
    </section>
  )
}

function Row({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-[0.62rem] font-medium uppercase tracking-[0.08em] text-(--ui-text-quaternary)">{label}</dt>
      <dd className="m-0 min-w-0">{children}</dd>
    </div>
  )
}
