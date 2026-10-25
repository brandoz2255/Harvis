import { useEffect, useRef } from 'react'

import { setDocFixSender } from '@/lib/harvis-doc-files'
import { setFollowupStarter } from '@/store/followups'
import { docSessionTarget } from '@/store/live-docs'
import { $sessionStates } from '@/store/session-states'

interface FollowupBridgeParams {
  startFreshSessionDraft: () => void
  submitText: (
    text: string,
    options?: { sessionId?: null | string; storedSessionId?: string }
  ) => Promise<unknown> | unknown
}

/**
 * Lets the follow-up cards (rendered deep in the composer dock) start a new
 * chat: a fresh draft, then the normal submit creates the backend session —
 * the same pair the Quick Entry "new session" target uses, so there is one
 * new-chat-and-send pipeline.
 *
 * The document panel's "Fix it" sends through the same submit, without a fresh
 * draft, into the chat that owns the document. A document whose chat is not live
 * is refused (`false`) rather than sent to whichever chat is in front.
 *
 * Registered once through refs: re-registering on callback identity churn
 * would leave a null-starter window where a click does nothing.
 */
export function useFollowupBridge({ startFreshSessionDraft, submitText }: FollowupBridgeParams): void {
  const startFreshRef = useRef(startFreshSessionDraft)
  startFreshRef.current = startFreshSessionDraft
  const submitTextRef = useRef(submitText)
  submitTextRef.current = submitText

  useEffect(() => {
    setFollowupStarter(prompt => {
      startFreshRef.current()

      return submitTextRef.current(prompt)
    })

    setDocFixSender((text, sessionId) => {
      if (sessionId === undefined) {
        return submitTextRef.current(text)
      }

      const target = docSessionTarget($sessionStates.get(), sessionId)

      return target ? submitTextRef.current(text, target) : false
    })

    return () => {
      setFollowupStarter(null)
      setDocFixSender(null)
    }
  }, [])
}
