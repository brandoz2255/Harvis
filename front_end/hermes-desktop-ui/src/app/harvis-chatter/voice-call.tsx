import { useStore } from '@nanostores/react'
import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { useI18n } from '@/i18n'
import { markVoiceSubmit } from '@/lib/voice-playback'
import { clearWakeIndicator, syncWakeIndicatorWithVoice } from '@/lib/wake-indicator'
import { $gateway } from '@/store/gateway'
import { notify } from '@/store/notifications'
import { $selectedStoredSessionId } from '@/store/session'
import {
  $voiceBusy,
  $voiceChatDrafts,
  $voiceTurns,
  loadVoiceSession,
  markVoiceReplySpoken,
  pendingVoiceReply,
  sendVoiceTurn,
  stopVoiceTurn,
  takeChatDrafts,
  warmVoiceModel
} from '@/store/voice-assistant'
import { $voiceCallCompact, $voiceCallLive, setVoiceCallCompact, setVoiceCallLive } from '@/store/voice-call'
import { $voiceStopPhrase } from '@/store/voice-prefs'
import { resumeWakeAfterVoice } from '@/store/wake-word'

import { requestComposerInsert } from '../chat/composer/focus'
import { HarvisVoiceOrb } from '../chat/composer/harvis-voice-orb'
import { useVoiceConversation } from '../chat/composer/hooks/use-voice-conversation'
import { appViewForPath, NEW_CHAT_ROUTE, sessionRoute } from '../routes'

import { runVoiceSteps } from './voice-steps'
import { VoiceTranscript } from './voice-transcript'

interface HarvisVoiceCallProps {
  transcribeAudio: (audio: Blob) => Promise<string>
}

function openChat(navigate: ReturnType<typeof useNavigate>) {
  const sessionId = $selectedStoredSessionId.get()

  navigate(sessionId ? sessionRoute(sessionId) : NEW_CHAT_ROUTE)
}

/**
 * The voice call with Harvis, started from the titlebar's Harvis button and
 * kept on every page. (The composer's voice button is the plain one: it talks
 * to the chat.) Talking to Harvis is "do this, do that": it answers in its own
 * little transcript on the call card and never posts into the chat you have open. "Open settings" moves the app; "type …"
 * or "put a list in my chat" drops text into the chat box, unsent, so you can
 * edit it and send it yourself. Several steps in one line run in order
 * (voice-steps.ts). Everything else goes to Harvis's own voice conversation
 * (store/voice-assistant.ts): a plain, fast model reply that starts no jobs.
 */
export function HarvisVoiceCall({ transcribeAudio }: HarvisVoiceCallProps) {
  const { t } = useI18n()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const live = useStore($voiceCallLive)
  const busy = useStore($voiceBusy)
  const compact = useStore($voiceCallCompact)
  const drafts = useStore($voiceChatDrafts)
  const hasTurns = useStore($voiceTurns).length > 0
  const onChat = appViewForPath(pathname) === 'chat'
  const wakePauseRef = useRef<Promise<void> | null>(null)
  const ownsIndicatorRef = useRef(false)

  const conversation = useVoiceConversation({
    beforeMicOpen: () => wakePauseRef.current ?? undefined,
    busy,
    consumePendingResponse: markVoiceReplySpoken,
    enabled: live,
    onFatalError: () => setVoiceCallLive(false),
    onInterrupt: stopVoiceTurn,
    onStopWord: () => setVoiceCallLive(false),
    onSubmit: text =>
      runVoiceSteps(text, {
        navigate,
        ask: async line => {
          markVoiceSubmit()
          await sendVoiceTurn(line, {
            page: `${appViewForPath(window.location.pathname)} (${window.location.pathname})`
          })
        }
      }),
    onTranscribeAudio: transcribeAudio,
    pendingResponse: pendingVoiceReply
  })

  const { level, muted, status, toggleMute } = conversation

  // The call's history comes back with it, and the wake-word listener lets go
  // of the mic for as long as the call holds it.
  useEffect(() => {
    if (!live) {
      return
    }

    void loadVoiceSession()
    warmVoiceModel()

    wakePauseRef.current = (async () => {
      try {
        await $gateway.get()?.request('wake.pause', {})
      } catch {
        // No wake listener: nothing held the mic.
      }
    })()

    const phrase = $voiceStopPhrase.get()

    if (phrase) {
      notify({ id: 'voice-stop-hint', kind: 'info', icon: 'mic', message: t.notifications.voice.sayStopToEnd(phrase) })
    }

    return () => {
      wakePauseRef.current = null
      stopVoiceTurn()
      void resumeWakeAfterVoice()
    }
  }, [live, t])

  useEffect(() => {
    if (syncWakeIndicatorWithVoice(live, status)) {
      ownsIndicatorRef.current = live
    }
  }, [live, status])

  useEffect(
    () => () => {
      if (ownsIndicatorRef.current) {
        clearWakeIndicator()
      }
    },
    []
  )

  // Text Harvis wrote for the chat goes into the chat box, never sent. Off the
  // chat it opens the chat first; the composer needs a moment to mount.
  useEffect(() => {
    if (!drafts.length) {
      return
    }

    if (!onChat) {
      openChat(navigate)

      return
    }

    const timer = window.setTimeout(() => {
      for (const draft of takeChatDrafts()) {
        requestComposerInsert(draft, { mode: 'block', target: 'main' })
      }
    }, 250)

    return () => window.clearTimeout(timer)
  }, [drafts, navigate, onChat])

  if (!live) {
    return null
  }

  const asBubble = compact || !onChat

  return (
    <HarvisVoiceOrb
      compact={asBubble}
      level={level}
      muted={muted}
      onEnd={() => setVoiceCallLive(false)}
      onOpenChat={onChat ? undefined : () => openChat(navigate)}
      onToggleCompact={onChat ? () => setVoiceCallCompact(!compact) : undefined}
      onToggleMute={toggleMute}
      status={status}
      transcript={
        asBubble ? hasTurns ? <VoiceTranscript limit={3} /> : undefined : <VoiceTranscript className="min-h-0" />
      }
    />
  )
}
