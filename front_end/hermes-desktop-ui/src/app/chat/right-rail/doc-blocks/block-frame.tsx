import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

import type { DocBlockKind } from '@/lib/harvis-doc-blocks'

/** The card every block sits in: optional title and subtitle above the drawing. */
export function BlockFrame({
  children,
  className,
  kind,
  subtitle,
  title
}: {
  children: ReactNode
  className?: string
  kind: DocBlockKind
  subtitle?: string
  title?: string
}) {
  return (
    <figure
      className={cn('my-[0.9em] min-w-0 rounded-lg border border-border bg-card/40 p-3 text-foreground', className)}
      data-kind={kind}
      data-slot="doc-block"
    >
      {(title || subtitle) && (
        <figcaption className="mb-2">
          {title && <div className="text-[1em] font-semibold leading-snug">{title}</div>}
          {subtitle && <div className="text-[0.8em] text-muted-foreground">{subtitle}</div>}
        </figcaption>
      )}
      {children}
    </figure>
  )
}
