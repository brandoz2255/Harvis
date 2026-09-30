import { useStore } from '@nanostores/react'
import { type ReactNode, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

import { HarvisName } from '@/components/chat/harvis-wordmark'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'
import { iconSize, Maximize, MessageCircle, Mic, MicOff, PanelBottom, X } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { $voicePlayback } from '@/store/voice-playback'

import type { ConversationStatus } from './hooks/use-voice-conversation'
import { getElementAnalyser } from './voice-activity'

interface HarvisVoiceOrbProps {
  level: number
  muted: boolean
  status: ConversationStatus
  onEnd: () => void
  onToggleMute: () => void
  /** The small bottom bubble instead of the side card. */
  compact?: boolean
  /** Card ⇄ bubble on the chat page. */
  onToggleCompact?: () => void
  /** Off the chat page: open the chat (where Harvis puts text for you). */
  onOpenChat?: () => void
  /** Harvis's own side of the call: what you asked and what it did. */
  transcript?: ReactNode
}

/** 0..1 loudness of whatever Harvis is saying right now, from the playback element. */
function playbackLevel(analyser: AnalyserNode | null, buf: Uint8Array<ArrayBuffer> | null): number {
  if (!analyser || !buf) {
    return 0
  }

  analyser.getByteTimeDomainData(buf)
  let sum = 0

  for (let i = 0; i < buf.length; i++) {
    const v = (buf[i] - 128) / 128
    sum += v * v
  }

  return Math.min(1, Math.sqrt(sum / buf.length) * 4)
}

/**
 * The Harvis voice panel: the old OWUI call orb, ported. The face grows with
 * your voice while Harvis listens, pulses with its own voice while it speaks,
 * and spins a ring while it transcribes or thinks. Shown only during a voice
 * conversation; the composer keeps the real controls.
 */
export function HarvisVoiceOrb({
  compact = false,
  level,
  muted,
  onEnd,
  onOpenChat,
  onToggleCompact,
  onToggleMute,
  status,
  transcript
}: HarvisVoiceOrbProps) {
  const { t } = useI18n()
  const c = t.composer
  const playback = useStore($voicePlayback)
  const orbRef = useRef<HTMLDivElement | null>(null)
  const micRef = useRef(level)
  const statusRef = useRef({ muted, status })

  micRef.current = level
  statusRef.current = { muted, status }

  const speaking = status === 'speaking'
  const working = status === 'transcribing' || status === 'thinking'
  const listening = status === 'listening' && !muted
  const audioElement = playback.status === 'speaking' ? playback.audioElement : null

  // One animation loop writes --orb-level straight onto the element: the mic
  // level already arrives as state, but the playback level would otherwise
  // re-render the panel sixty times a second.
  useEffect(() => {
    const el = orbRef.current

    if (!el) {
      return
    }

    const analyser = audioElement ? (getElementAnalyser(audioElement)?.analyser ?? null) : null
    const buf = analyser ? new Uint8Array(analyser.fftSize) : null
    let smoothed = 0
    let raf = 0

    const tick = () => {
      const { muted: isMuted, status: now } = statusRef.current

      const target =
        now === 'speaking'
          ? playbackLevel(analyser, buf)
          : now === 'listening' && !isMuted
            ? Math.min(1, micRef.current * 1.6)
            : 0

      // Rise fast, fall slow — a voice meter, not a strobe.
      smoothed += (target - smoothed) * (target > smoothed ? 0.45 : 0.12)
      el.style.setProperty('--orb-level', smoothed.toFixed(3))
      raf = requestAnimationFrame(tick)
    }

    tick()

    return () => cancelAnimationFrame(raf)
  }, [audioElement, compact])

  const label = speaking
    ? c.speaking
    : status === 'transcribing'
      ? c.transcribing
      : status === 'thinking'
        ? c.thinking
        : muted
          ? c.muted
          : c.listening

  const dot = (
    <span
      aria-hidden="true"
      className={cn(
        'size-2 shrink-0 rounded-full',
        listening ? 'bg-emerald-500' : speaking ? 'bg-[#5b8def]' : working ? 'bg-amber-500' : 'bg-muted-foreground'
      )}
    />
  )

  const face = (
    <svg aria-hidden="true" className="size-full" viewBox="0 0 64 64">
      <defs>
        <filter height="200%" id="harvis-orb-glow" width="200%" x="-50%" y="-50%">
          <feGaussianBlur result="b" stdDeviation="1.1" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g fill="none" filter="url(#harvis-orb-glow)" stroke="#6FA0FF" strokeLinecap="round">
        <path d="M20 28 Q24 22 28 28" strokeWidth="3.4" />
        <path d="M36 28 Q40 22 44 28" strokeWidth="3.4" />
        <path className="harvis-orb-mouth" d="M24 39 Q32 46 40 39" strokeWidth="2.8" />
      </g>
    </svg>
  )

  if (compact) {
    return createPortal(
      <aside
        aria-label="Harvis voice"
        className="fixed bottom-4 left-1/2 z-60 flex -translate-x-1/2 items-center gap-2 rounded-2xl border border-border/60 bg-card/90 py-1.5 pr-1.5 pl-2 shadow-xl backdrop-blur-md"
        data-slot="harvis-voice-bubble"
        data-status={status}
      >
        {transcript && (
          <div className="absolute bottom-full left-1/2 mb-2 flex max-h-40 w-72 -translate-x-1/2 flex-col rounded-2xl border border-border/60 bg-card/95 p-2.5 shadow-xl backdrop-blur-md">
            {transcript}
          </div>
        )}
        <div className="relative grid size-9 shrink-0 place-items-center">
          {working && (
            <span
              aria-hidden="true"
              className="harvis-orb-arc absolute inset-0 rounded-full motion-safe:animate-spin"
            />
          )}
          <div
            className={cn('harvis-orb harvis-orb-sm size-7 rounded-full', muted && !speaking && 'opacity-55')}
            ref={orbRef}
          >
            {face}
          </div>
        </div>
        <div
          aria-live="polite"
          className="flex min-w-24 items-center gap-1.5 text-xs font-medium text-foreground/85"
          role="status"
        >
          {dot}
          {label}
        </div>
        <Button
          aria-label={muted ? c.unmuteMic : c.muteMic}
          aria-pressed={muted}
          className="size-7 rounded-full"
          onClick={onToggleMute}
          size="icon"
          type="button"
          variant={muted ? 'secondary' : 'ghost'}
        >
          {muted ? <MicOff className={iconSize.xs} /> : <Mic className={iconSize.xs} />}
        </Button>
        {onOpenChat && (
          <Button
            aria-label="Open chat"
            className="size-7 rounded-full text-muted-foreground hover:text-foreground"
            onClick={onOpenChat}
            size="icon"
            type="button"
            variant="ghost"
          >
            <MessageCircle className={iconSize.xs} />
          </Button>
        )}
        {onToggleCompact && (
          <Button
            aria-label="Expand voice panel"
            className="size-7 rounded-full text-muted-foreground hover:text-foreground"
            onClick={onToggleCompact}
            size="icon"
            type="button"
            variant="ghost"
          >
            <Maximize className={iconSize.xs} />
          </Button>
        )}
        <Button
          aria-label={c.endConversation}
          className="size-7 rounded-full text-muted-foreground hover:text-foreground"
          onClick={onEnd}
          size="icon"
          type="button"
          variant="ghost"
        >
          <X className={iconSize.xs} />
        </Button>
      </aside>,
      document.body
    )
  }

  return createPortal(
    <aside
      aria-label="Harvis voice"
      className={cn(
        'fixed z-60 flex flex-col items-center gap-4 rounded-3xl border border-border/60 bg-card/85 px-5 pt-4 pb-5 shadow-2xl backdrop-blur-md',
        // The chat's own card keeps its size; Harvis's card is wider for its transcript.
        transcript ? 'w-72' : 'w-60',
        'top-1/2 right-4 -translate-y-1/2',
        'max-sm:top-14 max-sm:right-1/2 max-sm:w-52 max-sm:translate-x-1/2 max-sm:translate-y-0'
      )}
      data-slot="harvis-voice-orb"
      data-status={status}
    >
      <div className="flex w-full items-center justify-between">
        <HarvisName className="text-[0.7rem] text-muted-foreground" />
        <div className="flex items-center">
          {onToggleCompact && (
            <Button
              aria-label="Shrink to a bubble"
              className="size-7 rounded-full text-muted-foreground hover:text-foreground"
              onClick={onToggleCompact}
              size="icon"
              type="button"
              variant="ghost"
            >
              <PanelBottom className={iconSize.sm} />
            </Button>
          )}
          <Button
            aria-label={c.endConversation}
            className="size-7 rounded-full text-muted-foreground hover:text-foreground"
            onClick={onEnd}
            size="icon"
            type="button"
            variant="ghost"
          >
            <X className={iconSize.sm} />
          </Button>
        </div>
      </div>

      <div className="relative grid size-44 place-items-center max-sm:size-36">
        {speaking && (
          <span
            aria-hidden="true"
            className="absolute inset-3 rounded-full ring-2 ring-[#5b8def]/50 motion-safe:animate-ping"
          />
        )}
        {working && (
          <span aria-hidden="true" className="harvis-orb-arc absolute inset-1 rounded-full motion-safe:animate-spin" />
        )}
        <div
          className={cn('harvis-orb relative size-32 rounded-full max-sm:size-28', muted && !speaking && 'opacity-55')}
          ref={orbRef}
        >
          {face}
        </div>
      </div>

      <div aria-live="polite" className="flex items-center gap-2 text-sm font-medium text-foreground/85" role="status">
        {dot}
        {label}
      </div>

      <Button
        aria-label={muted ? c.unmuteMic : c.muteMic}
        aria-pressed={muted}
        className="h-8 gap-1.5 rounded-full px-3 text-xs"
        onClick={onToggleMute}
        type="button"
        variant={muted ? 'secondary' : 'ghost'}
      >
        {muted ? <MicOff className={iconSize.xs} /> : <Mic className={iconSize.xs} />}
        {muted ? c.unmuteMic : c.muteMic}
      </Button>

      {transcript && <div className="flex max-h-56 w-full flex-col border-t border-border/50 pt-3">{transcript}</div>}
    </aside>,
    document.body
  )
}
