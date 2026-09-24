import { useStore } from '@nanostores/react'
import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

import { HarvisName } from '@/components/chat/harvis-wordmark'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'
import { iconSize, Mic, MicOff, X } from '@/lib/icons'
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
export function HarvisVoiceOrb({ level, muted, onEnd, onToggleMute, status }: HarvisVoiceOrbProps) {
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
  }, [audioElement])

  const label = speaking
    ? c.speaking
    : status === 'transcribing'
      ? c.transcribing
      : status === 'thinking'
        ? c.thinking
        : muted
          ? c.muted
          : c.listening

  return createPortal(
    <aside
      aria-label="Harvis voice"
      className={cn(
        'fixed z-40 flex w-60 flex-col items-center gap-4 rounded-3xl border border-border/60 bg-card/85 px-5 pt-4 pb-5 shadow-2xl backdrop-blur-md',
        'top-1/2 right-4 -translate-y-1/2',
        'max-sm:top-14 max-sm:right-1/2 max-sm:w-52 max-sm:translate-x-1/2 max-sm:translate-y-0'
      )}
      data-slot="harvis-voice-orb"
      data-status={status}
    >
      <div className="flex w-full items-center justify-between">
        <HarvisName className="text-[0.7rem] text-muted-foreground" />
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
        </div>
      </div>

      <div aria-live="polite" className="flex items-center gap-2 text-sm font-medium text-foreground/85" role="status">
        <span
          aria-hidden="true"
          className={cn(
            'size-2 rounded-full',
            listening ? 'bg-emerald-500' : speaking ? 'bg-[#5b8def]' : working ? 'bg-amber-500' : 'bg-muted-foreground'
          )}
        />
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
    </aside>,
    document.body
  )
}
