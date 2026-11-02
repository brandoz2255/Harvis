import { useStore } from '@nanostores/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { $session, type HarvisUser, isWaiting, probeSession, startSessionWatch } from '@/lib/harvis-session'
import { claimUserScopedStorage } from '@/lib/user-scoped-storage'
import { idbArtStore } from '@/mods/island-art'

import { SignInScreen, UnreachableScreen, WaitingRoom } from './sign-in-screen'

/**
 * Nothing behind this gate mounts until the server says someone is signed in:
 * the app opens a gateway socket and a dozen queries on mount, and every one of
 * them would fail without a session.
 *
 * Once the app has mounted it stays mounted. If the session ends mid-use the
 * sign-in card covers the app instead of replacing it, so open drafts and the
 * current chat survive a re-sign-in.
 */
export function SessionGate({ children }: { children: ReactNode }) {
  const session = useStore($session)
  const [mounted, setMounted] = useState(false)
  const lastUser = useRef<HarvisUser | null>(null)

  useEffect(() => {
    void probeSession()
  }, [])

  useEffect(() => {
    // Waiting for the admin's approval: the server refuses everything but the
    // session probe, so nothing mounts until the role comes back approved.
    if (session.status !== 'signed-in' || isWaiting(session.user)) {
      return
    }

    // A different person signing in over someone else's open app must not see
    // their chats: start the app over instead of uncovering it.
    if (lastUser.current && lastUser.current.id !== session.user.id) {
      window.location.reload()

      return
    }

    // The browser's cached chats belong to whoever last signed in here, and an
    // expired session never signed out to clear them. Wipe and restart before
    // anything mounts; a blocked IndexedDB never answers, so stop waiting.
    if (claimUserScopedStorage(session.user.id) === 'switched') {
      void Promise.race([idbArtStore.clear(), new Promise(resolve => setTimeout(resolve, 500))]).then(() =>
        window.location.reload()
      )

      return
    }

    lastUser.current = session.user
    setMounted(true)

    return startSessionWatch()
  }, [session])

  if (session.status === 'signed-in' && isWaiting(session.user)) {
    return <WaitingRoom user={session.user} />
  }

  if (!mounted) {
    // Signed in but not yet cleared to mount: the cache check above may still
    // restart the app, and nothing should read the old cache before then.
    if (session.status === 'checking' || session.status === 'signed-in') {
      return <div className="fixed inset-0 bg-(--ui-chat-surface-background)" />
    }

    if (session.status === 'unreachable') {
      return <UnreachableScreen detail={session.detail} onRetry={probeSession} />
    }

    if (session.status === 'signed-out') {
      return <SignInScreen />
    }
  }

  // A different person's session keeps the card up until the reload above has
  // replaced the app, so the previous user's chats are never uncovered.
  const covered =
    session.status === 'signed-out' ||
    (session.status === 'signed-in' && lastUser.current !== null && lastUser.current.id !== session.user.id)

  return (
    <>
      {/* `inert` keeps Tab and screen readers out of the app under the card. */}
      <div className="contents" inert={covered}>
        {children}
      </div>
      {covered && <SignInScreen expired previousUser={lastUser.current} />}
    </>
  )
}
