import { useStore } from '@nanostores/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { $session, type HarvisUser, probeSession, startSessionWatch } from '@/lib/harvis-session'

import { SignInScreen, UnreachableScreen } from './sign-in-screen'

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
    if (session.status !== 'signed-in') {
      return
    }

    // A different person signing in over someone else's open app must not see
    // their chats: start the app over instead of uncovering it.
    if (lastUser.current && lastUser.current.id !== session.user.id) {
      window.location.reload()

      return
    }

    lastUser.current = session.user
    setMounted(true)

    return startSessionWatch()
  }, [session])

  if (!mounted) {
    if (session.status === 'checking') {
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
