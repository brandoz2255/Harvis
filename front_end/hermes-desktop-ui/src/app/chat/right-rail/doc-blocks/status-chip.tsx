import { Children, isValidElement, type ReactNode } from 'react'

import { Badge, type BadgeProps } from '@/components/ui/badge'
import { type StatusTone, statusTone } from '@/lib/harvis-doc-blocks'
import { cn } from '@/lib/utils'

const TONES: Record<StatusTone, { className?: string; variant: BadgeProps['variant'] }> = {
  amber: { variant: 'warn' },
  blue: { className: 'bg-sky-500/15 text-sky-700 dark:text-sky-300', variant: 'default' },
  gray: { variant: 'muted' },
  green: { className: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300', variant: 'default' },
  red: { variant: 'destructive' }
}

/** Plain text of a React subtree: strings and numbers, through wrappers like <strong>. */
export function nodeText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') {
    return String(node)
  }

  return Children.toArray(node)
    .map(child => {
      if (typeof child === 'string' || typeof child === 'number') {
        return String(child)
      }

      return isValidElement<{ children?: ReactNode }>(child) ? nodeText(child.props.children) : ''
    })
    .join('')
}

export function StatusChip({ children, tone }: { children: ReactNode; tone: StatusTone }) {
  const { className, variant } = TONES[tone]

  return (
    <Badge className={cn('text-[0.75em]', className)} data-tone={tone} size="default" variant={variant}>
      {children}
    </Badge>
  )
}

/** A table cell's content, as a coloured chip when the whole text is a status word. */
export function StatusText({ children }: { children?: ReactNode }) {
  const text = nodeText(children)
  const tone = text.length <= 16 ? statusTone(text) : null

  return tone ? <StatusChip tone={tone}>{text.replace(/\*+/g, '').trim()}</StatusChip> : <>{children}</>
}
