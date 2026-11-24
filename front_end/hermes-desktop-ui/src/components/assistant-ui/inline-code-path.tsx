import { useStore } from '@nanostores/react'
import { type ComponentProps, useState } from 'react'

import { useSessionView } from '@/app/chat/session-view'
import { useI18n } from '@/i18n'
import { pathFromInlineCode } from '@/lib/inline-code-path'
import { normalizeOrLocalPreviewTarget } from '@/lib/local-preview'
import { cn } from '@/lib/utils'
import { notifyError } from '@/store/notifications'
import { openPreview } from '@/store/preview'

function codeText(children: unknown): string {
  return typeof children === 'string' ? children : Array.isArray(children) ? children.join('') : ''
}

/**
 * Inline code. A span that names a file (`src/app.ts`, `~/notes.md:12`) opens
 * that file in the side panel when clicked, the way an editor link would.
 *
 * Inline code must not vote when an ancestor resolves `dir="auto"` (HTML's
 * algorithm skips descendants that carry their own dir), mirroring the CSS
 * isolate that already keeps it out of the plaintext scan. Fenced code never
 * reaches this override; it goes through the code plugin's CodeCard path.
 */
export function InlineCode({ children, className, ...props }: ComponentProps<'code'>) {
  const path = pathFromInlineCode(codeText(children))

  if (!path) {
    return (
      <code className={className} dir="ltr" {...props}>
        {children}
      </code>
    )
  }

  return (
    <InlineCodePath className={className} path={path} {...props}>
      {children}
    </InlineCodePath>
  )
}

function InlineCodePath({ children, className, path, ...props }: ComponentProps<'code'> & { path: string }) {
  const { t } = useI18n()
  // Resolve against the cwd of the session this transcript belongs to.
  const cwd = useStore(useSessionView().$cwd)
  const [opening, setOpening] = useState(false)

  async function open() {
    if (opening) {
      return
    }

    setOpening(true)

    try {
      const target = await normalizeOrLocalPreviewTarget(path, cwd || undefined)

      if (!target) {
        throw new Error(`Could not open preview target: ${path}`)
      }

      openPreview(target, 'explicit-link')
    } catch (error) {
      notifyError(error, t.preview.unavailable)
    } finally {
      setOpening(false)
    }
  }

  return (
    <code
      {...props}
      aria-label={`${t.preview.openPreview}: ${path}`}
      className={cn(
        className,
        'cursor-pointer underline decoration-dotted decoration-1 underline-offset-2 hover:decoration-solid',
        opening && 'opacity-60'
      )}
      dir="ltr"
      onClick={() => void open()}
      onKeyDown={event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          void open()
        }
      }}
      role="button"
      tabIndex={0}
      title={t.preview.openPreview}
    >
      {children}
    </code>
  )
}
