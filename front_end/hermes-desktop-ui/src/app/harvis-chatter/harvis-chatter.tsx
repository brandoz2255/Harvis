import { useStore } from '@nanostores/react'
import { type FormEvent, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { ArrowUp, iconSize, Loader2, Mic, X } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { $selectedStoredSessionId } from '@/store/session'
import { loadVoiceSession, sendVoiceTurn } from '@/store/voice-assistant'
import { $harvisMicOn, $voiceCallLive } from '@/store/voice-call'

import { useVoiceRecorder } from '../chat/composer/hooks/use-voice-recorder'
import { appViewForPath, NEW_CHAT_ROUTE, sessionRoute } from '../routes'

import { runVoiceSteps } from './voice-steps'
import { VoiceTranscript } from './voice-transcript'

interface HarvisChatterProps {
  transcribeAudio: (audio: Blob) => Promise<string>
}

/**
 * A small Harvis pill at the bottom of every page, shown while the titlebar's
 * Harvis button is on. On the chat it sits at the right, just above the
 * composer, so it never covers it. Say or
 * type where to go ("open settings") and it takes you there; anything else goes
 * to Harvis's own conversation (the same one as the voice call) and the answer
 * shows above the pill, so you stay on the page you are on and your chats are
 * left alone. Text Harvis writes for the chat lands in the chat box, unsent.
 */
export function HarvisChatter({ transcribeAudio }: HarvisChatterProps) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const sessionId = useStore($selectedStoredSessionId)
  // A live voice call shows its own bubble in this spot.
  const voiceCallLive = useStore($voiceCallLive)
  // Hidden until Harvis is switched on from the titlebar button.
  const harvisOn = useStore($harvisMicOn)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [asked, setAsked] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const handle = async (raw: string) => {
    const text = raw.trim()

    if (!text) {
      return
    }

    setDraft('')
    setAsked(true)
    await runVoiceSteps(text, {
      navigate,
      ask: async line => {
        await loadVoiceSession()
        await sendVoiceTurn(line, {
          page: `${appViewForPath(window.location.pathname)} (${window.location.pathname})`
        })
      }
    })
  }

  const { dictate, voiceStatus } = useVoiceRecorder({
    focusInput: () => inputRef.current?.focus(),
    maxRecordingSeconds: 30,
    onTranscribeAudio: transcribeAudio,
    onTranscript: text => void handle(text)
  })

  useEffect(() => {
    if (open) {
      inputRef.current?.focus()
    }
  }, [open])

  if (!harvisOn || voiceCallLive) {
    return null
  }

  const onChat = appViewForPath(pathname) === 'chat'

  const listening = voiceStatus === 'recording'
  const transcribing = voiceStatus === 'transcribing'

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void handle(draft)
  }

  const openChat = () => {
    setAsked(false)
    navigate(sessionId ? sessionRoute(sessionId) : NEW_CHAT_ROUTE)
  }

  return (
    // z-60: above full-screen panels (Scheduled jobs, Settings …, z-50), below dialogs.
    <div
      className={cn(
        'pointer-events-none fixed inset-x-0 z-60 flex flex-col gap-2 px-4',
        onChat ? 'bottom-24 items-end' : 'bottom-4 items-center'
      )}
    >
      {asked && (
        <div className="pointer-events-auto flex max-h-56 w-full max-w-md flex-col gap-1 rounded-xl border border-(--stroke-nous) bg-(--ui-chat-bubble-background) px-3 py-2 shadow-nous">
          <div className="flex items-center justify-between">
            <button className="text-xs text-(--theme-primary) hover:underline" onClick={openChat} type="button">
              Open chat
            </button>
            <Button
              aria-label="Close reply"
              className="size-6 shrink-0 rounded-full text-muted-foreground"
              onClick={() => setAsked(false)}
              size="icon"
              variant="ghost"
            >
              <X className={iconSize.sm} />
            </Button>
          </div>
          <VoiceTranscript className="min-h-0" limit={4} />
        </div>
      )}

      {open ? (
        <form
          className="pointer-events-auto flex w-full max-w-md items-center gap-1 rounded-full border border-(--stroke-nous) bg-(--ui-chat-bubble-background) py-1 pl-4 pr-1 shadow-nous"
          onKeyDown={event => event.key === 'Escape' && setOpen(false)}
          onSubmit={onSubmit}
        >
          <input
            aria-label="Ask Harvis or say where to go"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            onChange={event => setDraft(event.target.value)}
            placeholder={listening ? 'Listening…' : transcribing ? 'Transcribing…' : 'Ask Harvis, or "open settings"'}
            ref={inputRef}
            value={draft}
          />
          <Button
            aria-label={listening ? 'Stop and send' : 'Speak to Harvis'}
            aria-pressed={listening}
            className={cn('size-8 rounded-full', listening && 'bg-red-500/15 text-red-500')}
            disabled={transcribing}
            onClick={dictate}
            size="icon"
            type="button"
            variant="ghost"
          >
            {transcribing ? (
              <Loader2 className={cn(iconSize.sm, 'motion-safe:animate-spin')} />
            ) : (
              <Mic className={iconSize.sm} />
            )}
          </Button>
          <Button aria-label="Send" className="size-8 rounded-full" disabled={!draft.trim()} size="icon" type="submit">
            <ArrowUp className={iconSize.sm} />
          </Button>
          <Button
            aria-label="Hide Harvis"
            className="size-8 rounded-full text-muted-foreground"
            onClick={() => setOpen(false)}
            size="icon"
            type="button"
            variant="ghost"
          >
            <X className={iconSize.sm} />
          </Button>
        </form>
      ) : (
        <button
          aria-label="Talk to Harvis"
          className="pointer-events-auto flex items-center gap-2 rounded-full border border-(--stroke-nous) bg-(--ui-chat-bubble-background) px-4 py-2 text-sm font-medium shadow-nous hover:bg-(--ui-chat-bubble-background)/80"
          onClick={() => setOpen(true)}
          type="button"
        >
          <Mic className={cn(iconSize.sm, 'text-(--theme-primary)')} /> Harvis
        </button>
      )}
    </div>
  )
}
