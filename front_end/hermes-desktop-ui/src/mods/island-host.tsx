// Renders the island in the app's own tree (src/island/mount.js) and keeps it in step with
// the app: it wears the app theme, a busy run thins its effects, and it stops drawing
// whenever nobody can see it. Because the island is same-origin and same-process, the
// signed-in account's own bots and game art go straight to the mounted app — there is no
// frame, no postMessage and nothing for a navigated page to intercept. The account id keys
// the host, so an account switch disposes the old island before the new one mounts.
import { useStore } from '@nanostores/react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { Codicon } from '@/components/ui/codicon'
import { mountIsland } from '@/island/mount.js'
import { $session } from '@/lib/harvis-session'
import { cn } from '@/lib/utils'
import { useRoster } from '@/plugins/hermes-bots/data'
import { openRosterBot } from '@/plugins/hermes-bots/roster-actions'
import { $busy } from '@/store/session'
import { useTheme } from '@/themes/context'

import { accountArtStore, type ArtView, IslandArt } from './island-art'
import { IslandBridge } from './island-bridge'
import { IslandRoster } from './island-roster'

// A re-probe after a 401 publishes a new session object for the same person; only a
// different (or signed-out) account makes in-flight work stale.
function isSameAccount(accountId: string) {
  const current = $session.get()

  return current.status === 'signed-in' && current.user.id === accountId
}

export function IslandHost() {
  const session = useStore($session)
  const accountId = session.status === 'signed-in' ? session.user.id : ''

  return accountId && session.status === 'signed-in' ? <AccountIslandHost accountId={accountId} key={accountId} /> : null
}

function AccountIslandHost({ accountId }: { accountId: string }) {
  const boxRef = useRef<HTMLDivElement>(null)
  const mountRef = useRef<HTMLDivElement>(null)
  const bridgeRef = useRef<IslandBridge | null>(null)
  const artRef = useRef<IslandArt | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [exploring, setExploring] = useState(false)
  // UI chrome fades in a beat after Explore opens, so the zoom-out lands first.
  const [uiIn, setUiIn] = useState(false)
  const [art, setArt] = useState<ArtView>({ custom: false, message: '', state: 'builtin' })
  const busy = useStore($busy)
  const { renderedMode, theme } = useTheme()
  const c = theme.colors

  useEffect(() => {
    if (!exploring) {
      setUiIn(false)
      return
    }
    const frame = requestAnimationFrame(() => setUiIn(true))
    return () => cancelAnimationFrame(frame)
  }, [exploring])

  // The island's residents are this account's configured bots. The query key carries the
  // account id so a switch never shows the previous account's cached roster.
  const isCurrent = () => isSameAccount(accountId)
  const { data } = useRoster(accountId, isCurrent)
  const rosterRef = useRef(new IslandRoster())
  const agents = rosterRef.current.update(data?.profiles ?? [])

  // A layout effect so its cleanup runs while the mount node is still attached: React
  // detaches refs before passive cleanups, and dispose() has to reach a live island.
  // Remounts only on Explore (the portal changes the node), matching the old frame reload.
  useLayoutEffect(() => {
    const mountEl = mountRef.current

    if (!mountEl) {
      return
    }

    const app = mountIsland(mountEl, {
      interactive: exploring,
      onSelect: agentId => {
        const stillCurrent = () => isSameAccount(accountId)
        const bot = stillCurrent() ? rosterRef.current.resolve(agentId) : undefined

        if (bot) {
          void openRosterBot(bot, { isCurrent: stillCurrent })
        }
      }
    })
    const bridge = new IslandBridge(app)
    const art_ = new IslandArt(app, accountArtStore(accountId), setArt)

    bridgeRef.current = bridge
    artRef.current = art_
    void art_.restore()

    const onVisibility = () => bridge.setReason('hidden', document.hidden)
    onVisibility()
    document.addEventListener('visibilitychange', onVisibility)

    const observer =
      typeof IntersectionObserver === 'undefined' || !boxRef.current
        ? null
        : new IntersectionObserver(entries => {
            const last = entries[entries.length - 1]

            if (last) {
              bridge.setReason('offscreen', !last.isIntersecting)
            }
          })

    if (observer && boxRef.current) {
      observer.observe(boxRef.current)
    }

    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      observer?.disconnect()
      art_.dispose()
      bridge.dispose()
      app.dispose()
      bridgeRef.current = null
      artRef.current = null
    }
  }, [accountId, exploring])

  useEffect(() => bridgeRef.current?.setSession(agents), [data, exploring])
  useEffect(() => bridgeRef.current?.setLowFx(busy), [busy, exploring])
  useEffect(
    () =>
      bridgeRef.current?.setTheme({
        colors: {
          background: c.background,
          border: c.border,
          foreground: c.foreground,
          mutedForeground: c.mutedForeground,
          popover: c.popover,
          primary: c.primary,
          primaryForeground: c.primaryForeground
        },
        mode: renderedMode
      }),
    [c.background, c.border, c.foreground, c.mutedForeground, c.popover, c.primary, c.primaryForeground, renderedMode, exploring]
  )

  const island = (
    <div
      className={cn(
        "group/island overflow-hidden",
        // Same node in both states so the zoom transition survives the switch.
        exploring ? "fixed inset-0 z-[100] bg-background" : "pointer-events-none absolute inset-0 z-10"
      )}
      data-slot="island"
      ref={boxRef}
    >
      <div
        className={cn(
          "island-map-frame absolute inset-0 motion-safe:transition-[transform,opacity] motion-safe:duration-700 motion-safe:ease-out",
          !exploring && "island-faded",
          // Faded state: the map is a real round pool rather than a rectangular image. The
          // circle uses viewport units so it stays circular at wide chat aspect ratios; its
          // outer half is entirely feathered into the Harvis canvas.
          exploring
            ? "scale-100 opacity-100"
            : "scale-[1.75] opacity-25 [mask-image:radial-gradient(circle_48vh_at_50%_46%,black_0,black_42%,rgba(0,0,0,.72)_58%,transparent_92%)] [&.hi-root]:bg-transparent [&_.hi-canvas]:border-0"
        )}
        ref={mountRef}
      />
      {!exploring && <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-10"
        // Pixel-fog: a low-contrast, blocky atmospheric layer that inherits the live Harvis
        // palette. It hides the last trace of the radial edge without painting a rectangle.
        style={{
          backgroundImage: 'radial-gradient(circle 48vh at 50% 46%, transparent 18%, color-mix(in srgb, var(--background) 18%, transparent) 45%, var(--background) 89%), repeating-linear-gradient(0deg, transparent 0 5px, color-mix(in srgb, var(--muted-foreground) 7%, transparent) 5px 7px), repeating-linear-gradient(90deg, transparent 0 7px, color-mix(in srgb, var(--muted-foreground) 5%, transparent) 7px 9px)',
          imageRendering: 'pixelated',
        }}
      />}

      {exploring && <div className={cn("absolute inset-x-0 bottom-0 flex items-center gap-2 bg-background/85 px-2 py-1 text-xs text-muted-foreground transition-opacity duration-300 delay-200 motion-reduce:transition-none", uiIn ? "opacity-100" : "opacity-0")} role="status">
        <span>
          {art.state === 'loading' && 'Loading your game art…'}
          {art.state === 'error' && (art.message || 'Those files could not be used.')}
          {art.state === 'custom' && 'Drawing with your own game art. It stays in this browser.'}
          {art.state === 'builtin' && (art.message || 'Built-in art. The residents are your account bots.')}
        </span>
        <input
          className="hidden"
          multiple
          onChange={event => {
            const files = event.target.files

            if (files?.length) {
              void artRef.current?.pick(files)
            }

            event.target.value = ''
          }}
          ref={fileRef}
          type="file"
          {...{ webkitdirectory: '' }}
        />
        <button className="underline" onClick={() => fileRef.current?.click()} type="button">Use my game art</button>
        {art.custom && <button className="underline" onClick={() => artRef.current?.clear()} type="button">Use built-in art</button>}
      </div>}
      {exploring && <button
        aria-label="Return to bot island"
        className={cn("absolute right-1 top-14 inline-flex size-5 items-center justify-center rounded bg-background/70 text-muted-foreground transition-opacity duration-300 delay-200 hover:text-foreground motion-reduce:transition-none", uiIn ? "opacity-100" : "opacity-0")}
        onClick={() => setExploring(false)}
        type="button"
      >
        <Codicon name="close" size="0.7rem" />
      </button>}
      <button
        className={cn(
          'pointer-events-auto absolute z-20 rounded border border-border bg-background/90 px-3 py-1 text-sm text-foreground',
          exploring
            ? cn("left-4 top-14 transition-opacity duration-300 delay-200 motion-reduce:transition-none", uiIn ? "opacity-100" : "opacity-0")
            : 'top-4 left-4'
        )}
        onClick={() => setExploring(value => !value)}
        type="button"
      >
        {exploring ? 'Back to bots' : 'Explore'}
      </button>
    </div>
  )

  return island
}
