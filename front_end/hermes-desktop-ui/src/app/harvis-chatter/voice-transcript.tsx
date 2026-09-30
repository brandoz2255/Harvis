import { useStore } from '@nanostores/react'
import { useEffect, useRef } from 'react'

import { cn } from '@/lib/utils'
import {
  $voiceTurns,
  resetVoiceSession,
  spokenVoiceText,
  voiceChatDrafts,
  type VoiceTurn
} from '@/store/voice-assistant'

interface VoiceTranscriptProps {
  className?: string
  /** How many of the latest lines to show. */
  limit?: number
}

function TurnLine({ turn }: { turn: VoiceTurn }) {
  const said = spokenVoiceText(turn.text).trim()
  const drafts = turn.role === 'assistant' && !turn.pending ? voiceChatDrafts(turn.text) : []

  if (turn.role === 'user') {
    return <p className="m-0 self-end rounded-xl bg-accent/60 px-2.5 py-1 text-foreground/80">{turn.text}</p>
  }

  return (
    <div className="flex flex-col gap-1">
      <p className="m-0 text-foreground/90">
        {said || (turn.pending ? <span className="text-muted-foreground">…</span> : null)}
      </p>
      {drafts.map((draft, i) => (
        <p
          className="m-0 line-clamp-3 rounded-lg border border-dashed border-border px-2 py-1 text-muted-foreground"
          key={i}
          title={draft}
        >
          In your chat box: {draft}
        </p>
      ))}
    </div>
  )
}

/** The voice assistant's own little conversation (store/voice-assistant.ts). */
export function VoiceTranscript({ className, limit = 8 }: VoiceTranscriptProps) {
  const turns = useStore($voiceTurns)
  const endRef = useRef<HTMLDivElement | null>(null)
  const shown = turns.slice(-limit)
  const last = shown.at(-1)

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [last?.id, last?.text])

  if (!shown.length) {
    return (
      <p className={cn('m-0 text-center text-xs text-muted-foreground', className)}>
        Tell Harvis what to do, like "open settings" or "put a grocery list in my chat".
      </p>
    )
  }

  return (
    <div
      aria-live="polite"
      className={cn('flex flex-col gap-1.5 overflow-y-auto text-xs leading-snug', className)}
      data-slot="voice-transcript"
    >
      {shown.map(turn => (
        <TurnLine key={turn.id} turn={turn} />
      ))}
      <button
        className="self-center text-[0.65rem] text-muted-foreground hover:text-foreground hover:underline"
        onClick={() => void resetVoiceSession()}
        type="button"
      >
        Start over
      </button>
      <div ref={endRef} />
    </div>
  )
}
