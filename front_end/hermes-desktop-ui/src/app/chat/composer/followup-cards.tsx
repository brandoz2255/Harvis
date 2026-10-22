import { composerFloatingPill } from '@/components/chat/composer-dock'
import { Codicon } from '@/components/ui/codicon'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import { useSessionSlice } from '@/lib/use-session-slice'
import { cn } from '@/lib/utils'
import { $followupsBySession, clearSessionFollowups, type Followup, startFollowup } from '@/store/followups'

/**
 * Suggested next steps for the turn that just ended, docked above the composer
 * (not inside the thread: the dock is the one surface that stays pinned to the
 * viewport while the transcript scrolls). "Start" opens a new chat seeded with
 * the card's prompt; the x retires the whole set. The store drops them when
 * the session's next turn begins.
 *
 * Same pointer-events rule as the pill strip: NEVER `pointer-events-none` — the
 * pop-out drag region sits behind it.
 */
export function FollowupCards({ sessionId }: { sessionId: null | string }) {
  const { t } = useI18n()
  const items = useSessionSlice($followupsBySession, sessionId)

  if (!sessionId || items.length === 0) {
    return null
  }

  const copy = t.composer

  return (
    <div className="flex items-start gap-1.5 px-[5px] pb-1.5" data-slot="followup-cards">
      <ul className="flex min-w-0 flex-1 flex-col gap-1">
        {items.map((item: Followup) => (
          <li
            className={cn(
              'flex min-h-(--composer-control-size) items-center gap-2 rounded-xl border border-border/65 py-0.5 pr-1 pl-2.5',
              'bg-(--composer-fill) backdrop-blur-[0.75rem] [-webkit-backdrop-filter:blur(0.75rem)]'
            )}
            key={`${item.title}\0${item.prompt}`}
          >
            <Codicon className="shrink-0 opacity-70" name="lightbulb" size="0.75rem" />
            <span className="min-w-0 flex-1 truncate text-xs text-(--ui-text-secondary)" title={item.prompt}>
              {item.title}
            </span>
            <button
              aria-label={copy.followupStartAria(item.title)}
              className={cn(composerFloatingPill, 'h-6 gap-1 px-2')}
              onClick={() => {
                if (startFollowup(sessionId, item)) {
                  triggerHaptic('selection')
                }
              }}
              type="button"
            >
              {copy.followupStart}
              <Codicon className="shrink-0 opacity-70" name="arrow-right" size="0.7rem" />
            </button>
          </li>
        ))}
      </ul>
      <Tip label={copy.followupDismiss}>
        <button
          aria-label={copy.followupDismiss}
          className={cn(composerFloatingPill, 'size-(--composer-control-size) justify-center px-0')}
          onClick={() => clearSessionFollowups(sessionId)}
          type="button"
        >
          <Codicon className="shrink-0 opacity-70" name="close" size="0.75rem" />
        </button>
      </Tip>
    </div>
  )
}
