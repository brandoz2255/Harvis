import { useStore } from '@nanostores/react'
import type * as React from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { PageLoader } from '@/components/page-loader'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  approvePairing,
  dismissPairing,
  getMessagingPlatforms,
  getPairing,
  type MessagingPlatformInfo,
  type MessagingPlatformsResponse,
  type PairingUser,
  revokePairing,
  testMessagingPlatform,
  updateMessagingPlatform
} from '@/hermes'
import { useI18n } from '@/i18n'
import { normalize } from '@/lib/text'
import { $changeEventsAvailable, $pairingChangeTick, $platformsChangeTick } from '@/store/live-sync'
import { notify, notifyError } from '@/store/notifications'
import { $settingsRequestProfile } from '@/store/settings-scope'

import { useRefreshHotkey } from '../hooks/use-refresh-hotkey'
import { useRouteEnumParam } from '../hooks/use-route-enum-param'
import { DetailColumn, ListColumn, MasterDetail } from '../master-detail'
import { PageSearchShell } from '../page-search-shell'
import { SettingsProfileScope } from '../settings/profile-scope'
import type { SetStatusbarItemGroup } from '../shell/statusbar-controls'

import { byPlatform, type EditMap, pairingKey, pairingLabel, PlatformRow, trimEdits } from './parts'
import { PlatformActionBar, PlatformDetail, type TestResult } from './platform-detail'

interface MessagingViewProps extends React.ComponentProps<'section'> {
  setStatusbarItemGroup?: SetStatusbarItemGroup
}

type GatewayInfo = Omit<MessagingPlatformsResponse, 'platforms'>

export function MessagingView({ setStatusbarItemGroup: _setStatusbarItemGroup, ...props }: MessagingViewProps) {
  const { t } = useI18n()
  const m = t.messaging
  // Shared settings "Applies to" scope, request-shaped (undefined → follow
  // the active profile; the API helpers treat null as "target primary").
  const scopeProfile = useStore($settingsRequestProfile)
  const [platforms, setPlatforms] = useState<MessagingPlatformInfo[] | null>(null)
  const [gateway, setGateway] = useState<GatewayInfo>({})
  const [testResult, setTestResult] = useState<TestResult | null>(null)

  const [pairing, setPairing] = useState<{ approved: PairingUser[]; pending: PairingUser[] }>({
    approved: [],
    pending: []
  })

  const [approving, setApproving] = useState<null | string>(null)
  const [pendingRevoke, setPendingRevoke] = useState<null | PairingUser>(null)
  const [edits, setEdits] = useState<EditMap>({})
  const [query, setQuery] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [saving, setSaving] = useState<string | null>(null)
  const platformIds = useMemo(() => platforms?.map(p => p.id) ?? [], [platforms])
  const [selectedId, setSelectedId] = useRouteEnumParam('platform', platformIds, platformIds[0] ?? '')

  const refreshPlatforms = useCallback(
    async (silent = false) => {
      if (!silent) {
        setRefreshing(true)
      }

      try {
        const { platforms: rows, ...info } = await getMessagingPlatforms(scopeProfile)
        // Platforms Harvis can run first; catalog order otherwise (sort is stable).
        setPlatforms([...rows].sort((a, b) => Number(b.supported !== false) - Number(a.supported !== false)))
        setGateway(info)
      } catch (err) {
        if (!silent) {
          notifyError(err, m.loadFailed)
        }
      } finally {
        if (!silent) {
          setRefreshing(false)
        }
      }
    },
    [m, scopeProfile]
  )

  // Pairing has its own signal. platforms.changed tracks connect/disconnect
  // health via gateway_state.json, which a new pairing request never moves —
  // riding it would leave a pending row invisible until something unrelated
  // reconnected. Failures stay silent: an older backend without the endpoint
  // should show no rows, not an error banner over a working page.
  const refreshPairing = useCallback(async () => {
    try {
      const result = await getPairing(scopeProfile)
      setPairing({ approved: result.approved ?? [], pending: result.pending ?? [] })
    } catch {
      // Leave the last known rows in place rather than blanking them.
    }
  }, [scopeProfile])

  const refreshAll = useCallback(
    async (silent = false) => {
      await Promise.all([refreshPlatforms(silent), refreshPairing()])
    },
    [refreshPairing, refreshPlatforms]
  )

  useRefreshHotkey(() => void refreshAll())

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  // Scope switch: the mounted list still shows the PREVIOUS profile's
  // platforms/pairing while the new fetch is in flight — blank it so stale
  // rows can't be toggled against the wrong backend.
  const scopeSeenRef = useRef(scopeProfile)

  // eslint-disable-next-line no-restricted-syntax -- legitimate non-atom ref write (scope-change guard)
  useEffect(() => {
    if (scopeSeenRef.current === scopeProfile) {
      return
    }

    scopeSeenRef.current = scopeProfile
    setPlatforms(null)
    setPairing({ approved: [], pending: [] })
    setEdits({})
  }, [scopeProfile])

  const changeEventsAvailable = useStore($changeEventsAvailable)
  const platformsChangeTick = useStore($platformsChangeTick)
  const pairingChangeTick = useStore($pairingChangeTick)

  // A new pending request (or a grant from another surface) moves the pairing
  // store on disk; the change watcher turns that into pairing.changed.
  useEffect(() => {
    if (!changeEventsAvailable || pairingChangeTick === 0 || document.hidden) {
      return
    }

    void refreshPairing()
  }, [changeEventsAvailable, pairingChangeTick, refreshPairing])

  // Connection status updates without a manual "check" click. platforms.changed
  // (the gateway persisting connect/disconnect/health to gateway_state.json)
  // drives the refresh on event-capable backends — no timer; older backends
  // keep the legacy visible-tab poll.
  useEffect(() => {
    if (!changeEventsAvailable || platformsChangeTick === 0 || document.hidden) {
      return
    }

    void refreshPlatforms(true)
  }, [changeEventsAvailable, platformsChangeTick, refreshPlatforms])

  useEffect(() => {
    if (changeEventsAvailable) {
      return
    }

    let cancelled = false

    function tick() {
      if (cancelled || document.hidden) {
        return
      }

      void refreshAll(true)
    }

    const id = window.setInterval(tick, 6000)

    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [changeEventsAvailable, refreshAll])

  const selected = useMemo(() => {
    if (!platforms) {
      return null
    }

    return platforms.find(platform => platform.id === selectedId) || platforms[0] || null
  }, [platforms, selectedId])

  const pendingByPlatform = useMemo(() => byPlatform(pairing.pending), [pairing.pending])
  const approvedByPlatform = useMemo(() => byPlatform(pairing.approved), [pairing.approved])

  const visiblePlatforms = useMemo(() => {
    if (!platforms) {
      return []
    }

    const q = normalize(query)

    if (!q) {
      return platforms
    }

    return platforms.filter(platform =>
      [platform.id, platform.name, platform.description, platform.state]
        .filter(Boolean)
        .some(value => String(value).toLowerCase().includes(q))
    )
  }, [platforms, query])

  // The backend says whether the gateway picked the change up; a save that
  // could not be applied is a warning, not a success.
  function notifySaved(title: string, result: { gateway_applied?: boolean; message?: string }) {
    notify({ kind: result.gateway_applied === false ? 'warning' : 'success', title, message: result.message || '' })
  }

  async function handleTest(platform: MessagingPlatformInfo) {
    setSaving(`test:${platform.id}`)

    try {
      const result = await testMessagingPlatform(platform.id, scopeProfile)
      setTestResult({ message: result.message, ok: result.ok, platformId: platform.id })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setTestResult({ message: `Test failed: ${message}`, ok: false, platformId: platform.id })
    } finally {
      setSaving(null)
    }
  }

  async function handleDismiss(user: PairingUser) {
    if (!user.request_id) {
      return
    }

    const key = pairingKey(user)
    const snapshot = pairing
    setPairing(current => ({
      approved: current.approved,
      pending: current.pending.filter(row => pairingKey(row) !== key)
    }))

    try {
      await dismissPairing(user.platform, user.request_id, scopeProfile)
      await refreshPairing()
    } catch (err) {
      setPairing(snapshot)
      notifyError(err, `Failed to dismiss ${pairingLabel(user)}`)
    }
  }

  async function handleToggle(platform: MessagingPlatformInfo, enabled: boolean) {
    setSaving(`enabled:${platform.id}`)

    try {
      const result = await updateMessagingPlatform(platform.id, { enabled }, scopeProfile)
      setPlatforms(current => current?.map(row => (row.id === platform.id ? { ...row, enabled } : row)) ?? current)
      notifySaved(enabled ? m.platformEnabled(platform.name) : m.platformDisabled(platform.name), result)
      await refreshPlatforms(true)
    } catch (err) {
      notifyError(err, m.failedUpdate(platform.name))
    } finally {
      setSaving(null)
    }
  }

  async function handleSave(platform: MessagingPlatformInfo) {
    const env = trimEdits(edits[platform.id] || {})

    if (Object.keys(env).length === 0) {
      return
    }

    setSaving(`env:${platform.id}`)

    try {
      const result = await updateMessagingPlatform(platform.id, { env }, scopeProfile)
      setEdits(current => ({ ...current, [platform.id]: {} }))
      await refreshPlatforms()
      notifySaved(m.setupSaved(platform.name), result)
    } catch (err) {
      notifyError(err, m.failedSave(platform.name))
    } finally {
      setSaving(null)
    }
  }

  async function handleClear(platform: MessagingPlatformInfo, key: string) {
    setSaving(`clear:${key}`)

    try {
      await updateMessagingPlatform(platform.id, { clear_env: [key] }, scopeProfile)
      setEdits(current => ({
        ...current,
        [platform.id]: {
          ...(current[platform.id] || {}),
          [key]: ''
        }
      }))
      await refreshPlatforms()
      notify({ kind: 'success', title: m.keyCleared(key), message: m.setupUpdated(platform.name) })
    } catch (err) {
      notifyError(err, m.failedClear(key))
    } finally {
      setSaving(null)
    }
  }

  // Approve/revoke paint from a snapshot immediately, then let the
  // authoritative refresh have the last word. A failed write restores the
  // snapshot so the row never silently disappears on an error.
  async function handleApprove(user: PairingUser) {
    if (!user.request_id) {
      return
    }

    const key = pairingKey(user)
    const snapshot = pairing
    setApproving(key)
    setPairing(current => ({
      approved: current.approved,
      pending: current.pending.filter(row => pairingKey(row) !== key)
    }))

    try {
      await approvePairing(user.platform, user.request_id, scopeProfile)
      notify({ kind: 'success', title: m.approvedUser(pairingLabel(user)), message: m.approvedHint })
      await refreshPairing()
    } catch (err) {
      setPairing(snapshot)
      // 429 is the code path's brute-force lockout — a distinct condition the
      // operator can only wait out, so it gets its own message.
      const lockedOut = err instanceof Error && err.message.includes('429')
      notifyError(err, lockedOut ? m.pairingLockedOut : m.failedApprove(pairingLabel(user)))
    } finally {
      setApproving(null)
    }
  }

  // ConfirmDialog owns the pending → done → close beat and shows an inline
  // error when onConfirm throws, so this rethrows instead of swallowing.
  async function handleRevoke(user: PairingUser) {
    const key = pairingKey(user)
    const snapshot = pairing
    setPairing(current => ({
      approved: current.approved.filter(row => pairingKey(row) !== key),
      pending: current.pending
    }))

    try {
      await revokePairing(user.platform, user.user_id, scopeProfile)
      notify({ kind: 'success', title: m.revokedUser(pairingLabel(user)), message: user.platform })
      await refreshPairing()
    } catch (err) {
      setPairing(snapshot)
      throw err
    }
  }

  return (
    <PageSearchShell
      {...props}
      onSearchChange={setQuery}
      searchHidden={(platforms?.length ?? 0) === 0}
      searchHints={platforms?.slice(0, 5).map(platform => t.common.tryHint(platform.name.toLowerCase()))}
      searchPlaceholder={m.search}
      searchValue={query}
    >
      {!platforms ? (
        <PageLoader label={m.loading} />
      ) : (
        <div className="flex h-full min-h-0 flex-col">
          {/* Which profile's gateway this page configures (hidden for
              single-profile users). */}
          <SettingsProfileScope className="border-b border-(--ui-stroke-secondary) px-3 py-2" />
          {gateway.gateway_reachable === false && gateway.gateway_error && (
            <div
              className="border-b border-(--ui-stroke-secondary) bg-amber-500/10 px-3 py-2 text-xs leading-5 text-amber-700 dark:text-amber-300"
              role="alert"
            >
              <span className="font-medium">Messaging gateway unavailable.</span> {gateway.gateway_error}
            </div>
          )}
          <div className="min-h-0 flex-1">
            <MasterDetail>
              <ListColumn>
                <ul className="space-y-1">
                  {visiblePlatforms.map(platform => (
                    <li key={platform.id}>
                      <PlatformRow
                        active={selected?.id === platform.id}
                        onSelect={() => setSelectedId(platform.id)}
                        pendingCount={pendingByPlatform[platform.id]?.length ?? 0}
                        platform={platform}
                      />
                    </li>
                  ))}
                </ul>
              </ListColumn>

              <DetailColumn
                actionBar={
                  selected && (
                    <PlatformActionBar
                      hasEdits={Object.keys(trimEdits(edits[selected.id] || {})).length > 0}
                      onSave={() => void handleSave(selected)}
                      onTest={() => void handleTest(selected)}
                      onToggle={enabled => void handleToggle(selected, enabled)}
                      platform={selected}
                      saving={saving}
                    />
                  )
                }
              >
                {selected && (
                  <PlatformDetail
                    approved={approvedByPlatform[selected.id] ?? []}
                    approving={approving}
                    edits={edits[selected.id] || {}}
                    onApprove={user => void handleApprove(user)}
                    onClear={key => void handleClear(selected, key)}
                    onDismiss={user => void handleDismiss(user)}
                    onEdit={(key, value) =>
                      setEdits(current => ({
                        ...current,
                        [selected.id]: {
                          ...(current[selected.id] || {}),
                          [key]: value
                        }
                      }))
                    }
                    onRevoke={setPendingRevoke}
                    pending={pendingByPlatform[selected.id] ?? []}
                    platform={selected}
                    saving={saving}
                    testResult={testResult}
                  />
                )}
              </DetailColumn>
            </MasterDetail>
          </div>
        </div>
      )}

      <ConfirmDialog
        busyLabel={m.revoking}
        cancelLabel={t.common.cancel}
        confirmLabel={m.revoke}
        description={pendingRevoke ? m.revokeDesc(pairingLabel(pendingRevoke)) : null}
        destructive
        onClose={() => setPendingRevoke(null)}
        onConfirm={() => (pendingRevoke ? handleRevoke(pendingRevoke) : undefined)}
        open={Boolean(pendingRevoke)}
        title={m.revokeTitle}
      />
    </PageSearchShell>
  )
}
