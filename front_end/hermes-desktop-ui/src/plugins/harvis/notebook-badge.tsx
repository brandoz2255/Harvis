/** The label for anything that works only partly or is still being built. Always paired with a one-line reason. */

import { cn } from '@hermes/plugin-sdk'

export function UnderConstruction({ className, note }: { className?: string; note?: string }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full border border-amber-500/50 bg-amber-500/10 px-1.5 py-px text-[0.6rem] font-medium text-amber-600 dark:text-amber-400',
        className
      )}
      title={note}
    >
      Under construction
    </span>
  )
}
