import { useStore } from '@nanostores/react'
import type { ChangeEvent } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { codiconIcon } from '@/components/ui/codicon'
import { KbdCombo } from '@/components/ui/kbd'
import { Tip } from '@/components/ui/tooltip'
import { getHermesConfigDefaults, getHermesConfigRecord, saveHermesConfig } from '@/hermes'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import {
  Archive,
  Bell,
  Brain,
  Cpu,
  Download,
  Globe,
  Info,
  Keyboard,
  RefreshCw,
  Search,
  Terminal,
  Upload
} from '@/lib/icons'
import { isEditableTarget } from '@/lib/keybinds/combo'
import { typeToFocusChar } from '@/lib/keybinds/composer-focus-keys'
import { cn } from '@/lib/utils'
import { $commandPaletteOpen, openCommandPalettePage } from '@/store/command-palette'
import { confirm } from '@/store/confirm'
import { bindingsFor } from '@/store/keybinds'
import { notify, notifyError } from '@/store/notifications'

import { invalidateHermesConfig } from '../hooks/use-config-record'
import { useRouteEnumParam } from '../hooks/use-route-enum-param'
import { OverlayIconButton } from '../overlays/overlay-chrome'
import { OverlayMain, OverlayNav, type OverlayNavGroup, OverlaySplitLayout } from '../overlays/overlay-split-layout'
import { OverlayView } from '../overlays/overlay-view'
import { SKILLS_ROUTE } from '../routes'

import { AboutSettings } from './about-settings'
import { AppearanceSettings } from './appearance-settings'
import { ConfigSettings } from './config-settings'
import { HARVIS_SECTIONS } from './constants'
import { GatewaySettings } from './gateway-settings'
import { CodingEnginesSettings, HarvisProvidersSettings } from './harvis-providers-settings'
import { KeybindSettings } from './keybind-settings'
import { MemoryLearningSettings } from './memory-learning-settings'
import { MODEL_VIEW_LABELS, MODEL_VIEWS, type ModelView } from './model-views'
import { NotificationsSettings } from './notifications-settings'
import { PROVIDER_VIEWS, ProvidersSettings, type ProviderView } from './providers-settings'
import { SessionsSettings } from './sessions-settings'
import type { SettingsPageProps, SettingsView as SettingsViewId } from './types'

const SETTINGS_VIEWS: readonly SettingsViewId[] = [
  // Harvis: no Nous billing, API-keys page (env vars are the server's, read-only)
  // or desktop plugins, so those tabs are not routable either.
  ...HARVIS_SECTIONS.map(s => `config:${s.id}` as SettingsViewId),
  'providers',
  'harvis-memory',
  'gateway',
  // Legacy alias: the Connections page merged into Gateways. Kept in the enum
  // so saved `?tab=connections` deep links still resolve (redirected below).
  'connections',
  'keybinds',
  'notifications',
  'sessions',
  'about'
]

export function SettingsView({ onClose, onConfigSaved, onMainModelChanged }: SettingsPageProps) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { hash, pathname, search } = useLocation()

  // MCP moved out of Settings into Capabilities (/skills?tab=mcp). Keep old
  // `/settings?tab=mcp` deep links working — `useRouteEnumParam` would silently
  // coerce the unknown tab to the default view otherwise. Preserve `server=` so
  // an old bookmark still lands on (and highlights) the selected server.
  useEffect(() => {
    const params = new URLSearchParams(search)

    if (params.get('tab') === 'mcp') {
      const server = params.get('server')
      const suffix = server ? `&server=${encodeURIComponent(server)}` : ''
      navigate(`${SKILLS_ROUTE}?tab=mcp${suffix}`, { replace: true })
    }
  }, [navigate, search])

  const [activeView, setActiveView] = useRouteEnumParam('tab', SETTINGS_VIEWS, 'config:model' as SettingsViewId)

  // Connections merged into the unified Gateways page: land old
  // `?tab=connections` routes/bookmarks there instead of a dead entry.
  useEffect(() => {
    if (activeView === 'connections') {
      setActiveView('gateway')
    }
  }, [activeView, setActiveView])
  // Providers subnav (Accounts vs API keys) lives in its own param so each
  // sub-view is deep-linkable and survives a refresh.
  const [providerView, setProviderView] = useRouteEnumParam<ProviderView>('pview', PROVIDER_VIEWS, 'harvis')
  // Model settings are nested (main / fallback / mixture of agents / auxiliary);
  // each sub-page is deep-linkable the same way the provider views are.
  const [modelView] = useRouteEnumParam<ModelView>('mview', MODEL_VIEWS, 'main')

  // Jump to a section + its sub-view in one navigate. Two sequential setters
  // would each read the same stale `search` and the second would clobber the
  // first's `tab` — so the sub-view never opened on narrow screens.
  const openSubView = useCallback(
    (tab: SettingsViewId, param: string, value: string, fallback: string) => {
      const params = new URLSearchParams(search)
      params.set('tab', tab)

      if (value === fallback) {
        params.delete(param)
      } else {
        params.set(param, value)
      }

      const qs = params.toString()
      navigate({ hash, pathname, search: qs ? `?${qs}` : '' }, { replace: true })
    },
    [hash, navigate, pathname, search]
  )

  const openProviderView = useCallback(
    (view: ProviderView) => openSubView('providers', 'pview', view, 'harvis'),
    [openSubView]
  )

  const openModelView = useCallback(
    (view: ModelView) => openSubView('config:model' as SettingsViewId, 'mview', view, 'main'),
    [openSubView]
  )

  const importInputRef = useRef<HTMLInputElement | null>(null)
  // Bumped after an import or reset so the open config page re-seeds its draft
  // from the saved record instead of autosaving its stale copy back over it.
  const [configEpoch, setConfigEpoch] = useState(0)

  const afterConfigReplaced = async () => {
    await invalidateHermesConfig()
    setConfigEpoch(epoch => epoch + 1)
    onConfigSaved?.()
  }

  const importConfig = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''

    if (!file) {
      return
    }

    void file
      .text()
      .then(async text => {
        const parsed: unknown = JSON.parse(text)
        // Accept both an exported record and a `{config: {...}}` wrapper.
        const record =
          parsed && typeof parsed === 'object' && !Array.isArray(parsed) && 'config' in parsed
            ? (parsed as { config: unknown }).config
            : parsed

        if (!record || typeof record !== 'object' || Array.isArray(record)) {
          throw new Error(t.settings.config.invalidJson)
        }

        const result = await saveHermesConfig(record as Parameters<typeof saveHermesConfig>[0])

        if (!result.ok) {
          throw new Error(t.settings.config.autosaveFailed)
        }

        await afterConfigReplaced()
        triggerHaptic('success')
        notify({ kind: 'success', title: t.settings.config.imported, message: file.name })
      })
      .catch(err => notifyError(err, t.settings.config.invalidJson))
  }

  const exportConfig = async () => {
    try {
      const cfg = await getHermesConfigRecord()
      const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'hermes-config.json'
      a.click()
      URL.revokeObjectURL(url)
      triggerHaptic('success')
    } catch (err) {
      notifyError(err, t.settings.exportFailed)
    }
  }

  const resetConfig = async () => {
    const ok = await confirm({
      confirmLabel: t.settings.resetToDefaults,
      destructive: true,
      title: t.settings.resetConfirm
    })

    if (!ok) {
      return
    }

    try {
      await saveHermesConfig(await getHermesConfigDefaults())
      await afterConfigReplaced()
      triggerHaptic('success')
    } catch (err) {
      notifyError(err, t.settings.resetFailed)
    }
  }

  const navGroups: OverlayNavGroup[] = useMemo(
    () => [
      // Harvis: no Nous billing, remote-gateway registry, API-keys page or desktop plugins.
      ...HARVIS_SECTIONS.map(s => {
        const view = `config:${s.id}` as SettingsViewId

        if (s.id === 'model') {
          return {
            active: activeView === view,
            children: MODEL_VIEWS.map(mv => ({
              active: activeView === view && modelView === mv,
              icon: s.icon,
              id: `mview:${mv}`,
              label: MODEL_VIEW_LABELS[mv],
              onSelect: () => openModelView(mv)
            })),
            icon: s.icon,
            id: view,
            label: t.settings.sections[s.id] ?? s.label,
            onSelect: () => openModelView('main')
          }
        }

        return {
          active: activeView === view,
          icon: s.icon,
          id: view,
          label: t.settings.sections[s.id] ?? s.label,
          onSelect: () => setActiveView(view)
        }
      }),
      {
        active: activeView === 'notifications',
        icon: Bell,
        id: 'notifications',
        label: t.settings.nav.notifications,
        onSelect: () => setActiveView('notifications')
      },
      {
        active: activeView === 'providers',
        children: [
          {
            active: activeView === 'providers' && providerView === 'harvis',
            icon: Cpu,
            id: 'pview:harvis',
            label: 'Models',
            onSelect: () => openProviderView('harvis')
          },
          {
            active: activeView === 'providers' && providerView === 'engines',
            icon: Terminal,
            id: 'pview:engines',
            label: 'Coding engines',
            onSelect: () => openProviderView('engines')
          },
          {
            active: activeView === 'providers' && providerView === 'custom-endpoints',
            icon: Globe,
            id: 'pview:custom-endpoints',
            label: t.settings.nav.providerCustomEndpoints,
            onSelect: () => openProviderView('custom-endpoints')
          }
        ],
        icon: Globe,
        id: 'providers',
        label: t.settings.nav.providers,
        onSelect: () => openProviderView('harvis')
      },
      {
        active: activeView === 'harvis-memory',
        icon: Brain,
        id: 'harvis-memory',
        label: 'Memory & skills',
        onSelect: () => setActiveView('harvis-memory')
      },
      {
        active: activeView === 'keybinds',
        icon: Keyboard,
        id: 'keybinds',
        label: t.settings.nav.keybinds,
        onSelect: () => setActiveView('keybinds')
      },
      {
        active: activeView === 'sessions',
        icon: Archive,
        id: 'sessions',
        label: t.settings.nav.archivedChats,
        onSelect: () => setActiveView('sessions')
      },
      {
        active: activeView === 'about',
        gapBefore: true,
        icon: Info,
        id: 'about',
        label: t.settings.nav.about,
        onSelect: () => setActiveView('about')
      }
    ],
    [activeView, modelView, providerView, t, setActiveView, openProviderView, openModelView]
  )

  // Type-to-search: printable keystrokes on the Settings surface (outside any
  // field) open the settings-scoped palette, seeded with the character — same
  // reflex as the chat surface's type-to-focus, pointed at search instead.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ($commandPaletteOpen.get() || isEditableTarget(event.target)) {
        return
      }

      const char = typeToFocusChar(event)

      if (char === null || char === ' ') {
        return
      }

      event.preventDefault()
      openCommandPalettePage('settings', char)
    }

    window.addEventListener('keydown', onKeyDown)

    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  // Fake search pill riding the card's top edge, dead-center and half off it.
  // Clicking (or just typing) opens the ⌘K palette scoped to settings; while
  // the palette is up the pill hands over to it — grows slightly and fades,
  // then fades back when the palette closes. It renders as chrome, not an
  // input — no border, recessed fill, live ⌘K hint.
  const searchCombo = bindingsFor('nav.commandPalette')[0]
  const paletteOpen = useStore($commandPaletteOpen)

  const searchPill = (
    <button
      className={cn(
        'flex h-(--titlebar-control-height) items-center gap-1.5 rounded-full border border-(--ui-stroke-secondary) bg-(--ui-chat-surface-background) px-2.5 text-(--ui-text-tertiary) shadow-sm transition-all duration-200 ease-out hover:text-foreground motion-reduce:transition-none',
        paletteOpen && 'pointer-events-none scale-110 opacity-0'
      )}
      onClick={() => {
        triggerHaptic('open')
        openCommandPalettePage('settings')
      }}
      tabIndex={paletteOpen ? -1 : undefined}
      type="button"
    >
      <Search className="size-3" />
      <span className="text-xs">{t.settings.search.pill}</span>
      {searchCombo && <KbdCombo combo={searchCombo} size="sm" variant="ghost" />}
    </button>
  )

  const navFooter = (
    <>
      <Tip label={t.settings.exportConfig}>
        <OverlayIconButton onClick={() => void exportConfig()}>
          <Download />
        </OverlayIconButton>
      </Tip>
      <Tip label={t.settings.importConfig}>
        <OverlayIconButton
          onClick={() => {
            triggerHaptic('open')
            importInputRef.current?.click()
          }}
        >
          <Upload />
        </OverlayIconButton>
      </Tip>
      <Tip label={t.settings.resetToDefaults}>
        <OverlayIconButton
          className="hover:text-destructive"
          onClick={() => {
            triggerHaptic('warning')
            void resetConfig()
          }}
        >
          <RefreshCw />
        </OverlayIconButton>
      </Tip>
    </>
  )

  const activeSettingsContent =
    activeView === 'config:appearance' ? (
      <AppearanceSettings />
    ) : activeView === 'about' ? (
      <AboutSettings />
    ) : activeView === 'gateway' || activeView === 'connections' ? (
      // 'connections' renders the unified page too so the frame before
      // the alias redirect lands doesn't flash the fallback view.
      <GatewaySettings />
    ) : activeView === 'keybinds' ? (
      <KeybindSettings />
    ) : activeView.startsWith('config:') ? (
      <ConfigSettings
        activeSectionId={activeView.slice('config:'.length)}
        key={configEpoch}
        modelView={modelView}
        onConfigSaved={onConfigSaved}
        onMainModelChanged={onMainModelChanged}
      />
    ) : activeView === 'providers' && providerView === 'harvis' ? (
      <HarvisProvidersSettings />
    ) : activeView === 'providers' && providerView === 'engines' ? (
      <CodingEnginesSettings />
    ) : activeView === 'harvis-memory' ? (
      <MemoryLearningSettings onClose={onClose} />
    ) : activeView === 'providers' ? (
      <ProvidersSettings
        onClose={onClose}
        onConfigSaved={onConfigSaved}
        onMainModelChanged={onMainModelChanged}
        onViewChange={setProviderView}
        view={providerView}
      />
    ) : activeView === 'notifications' ? (
      <NotificationsSettings />
    ) : (
      <SessionsSettings />
    )

  return (
    <OverlayView closeLabel={t.settings.closeSettings} edgeBadge={searchPill} onClose={onClose}>
      <OverlaySplitLayout>
        <OverlayNav footer={navFooter} groups={navGroups} />

        <OverlayMain className="px-0 pb-0">{activeSettingsContent}</OverlayMain>
        <input
          accept=".json,application/json"
          className="hidden"
          onChange={importConfig}
          ref={importInputRef}
          type="file"
        />
      </OverlaySplitLayout>
    </OverlayView>
  )
}

export { SettingsView as SettingsPage }
