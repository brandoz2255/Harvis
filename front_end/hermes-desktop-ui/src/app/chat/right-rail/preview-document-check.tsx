import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'
import type { HarvisDocKind } from '@/lib/harvis-doc'
import { $docFixSender, type DocIssue, docFixMessage, primaryExt } from '@/lib/harvis-doc-files'
import { type DocCheckResult, fetchDocCheck } from '@/lib/harvis-doc-preview-api'
import { AlertCircle, Check, Loader2, X } from '@/lib/icons'
import { cn } from '@/lib/utils'

type CheckState =
  | { phase: 'checking' }
  | { phase: 'done'; result: DocCheckResult }
  | { message: string; phase: 'error' }
  | { phase: 'idle' }

const SEVERITY_CLASS: Record<DocIssue['severity'], string> = {
  error: 'text-destructive',
  warn: 'text-amber-600 dark:text-amber-400'
}

interface DocCheckStripProps {
  /** The document has finished streaming; checking half a document is noise. */
  complete: boolean
  kind: HarvisDocKind
  source: string
  title: string
}

/**
 * "Check" runs the backend quality check on the finished document and lists
 * what it found, grouped by where. "Fix it" sends the list back to the chat as
 * a revision request. Results belong to the source they were run on, so an
 * edit clears them.
 */
export function DocCheckStrip({ complete, kind, source, title }: DocCheckStripProps) {
  const { t } = useI18n()
  const copy = t.docPreview.check
  const sender = useStore($docFixSender)
  const [state, setState] = useState<CheckState>({ phase: 'idle' })
  const [vision, setVision] = useState(false)
  const [sent, setSent] = useState(false)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => {
    setState({ phase: 'idle' })
    setSent(false)

    return () => controller.current?.abort()
  }, [source, title])

  const issues = state.phase === 'done' ? state.result.issues : []

  const groups = useMemo(() => {
    const byWhere = new Map<string, DocIssue[]>()

    for (const issue of issues) {
      byWhere.set(issue.where, [...(byWhere.get(issue.where) ?? []), issue])
    }

    return [...byWhere]
  }, [issues])

  const run = async () => {
    controller.current?.abort()

    const own = new AbortController()

    controller.current = own
    setSent(false)
    setState({ phase: 'checking' })

    try {
      const result = await fetchDocCheck({ format: primaryExt(kind), signal: own.signal, source, title, vision })

      if (!own.signal.aborted) {
        setState({ phase: 'done', result: { ...result, issues: result.issues ?? [] } })
      }
    } catch (error) {
      if (!own.signal.aborted) {
        setState({ message: error instanceof Error ? error.message : String(error), phase: 'error' })
      }
    }
  }

  const fix = async () => {
    if (!sender || !issues.length) {
      return
    }

    setSent(true)

    try {
      await sender(docFixMessage(issues))
    } catch (error) {
      setSent(false)
      setState({ message: error instanceof Error ? error.message : String(error), phase: 'error' })
    }
  }

  const checking = state.phase === 'checking'
  const checked = state.phase === 'done' ? state.result.checked : null

  return (
    <div className="shrink-0 border-b border-border/40 px-3 py-1" data-slot="doc-check">
      <div className="flex items-center gap-2">
        <Button
          className="h-6 gap-1 px-2 text-[0.6875rem]"
          disabled={!complete || checking}
          onClick={() => void run()}
          size="sm"
          variant="outline"
        >
          {checking ? (
            <Loader2 className="size-3 animate-spin motion-reduce:animate-none" />
          ) : (
            <Check className="size-3" />
          )}
          <span>{checking ? copy.checking : copy.button}</span>
        </Button>
        <label className="flex min-w-0 items-center gap-1 text-[0.625rem] text-muted-foreground">
          <input
            checked={vision}
            className="size-3"
            disabled={checking}
            onChange={event => setVision(event.target.checked)}
            type="checkbox"
          />
          <span className="truncate">{copy.vision}</span>
        </label>
        {state.phase === 'done' && !issues.length && (
          <span className="ml-auto flex items-center gap-1 text-[0.6875rem] text-muted-foreground" role="status">
            <Check className="size-3" />
            {copy.none}
          </span>
        )}
        {state.phase === 'error' && (
          <span className="ml-auto flex min-w-0 items-center gap-1 text-[0.6875rem] text-destructive" role="alert">
            <AlertCircle className="size-3 shrink-0" />
            <span className="truncate" title={state.message}>
              {copy.failed}
            </span>
          </span>
        )}
      </div>

      {state.phase === 'done' && (
        <div className="mt-1 grid gap-1.5" data-slot="doc-check-results">
          {groups.length > 0 && (
            <ul className="grid max-h-40 gap-1.5 overflow-y-auto">
              {groups.map(([where, items]) => (
                <li key={where}>
                  <div className="text-[0.625rem] font-medium tracking-wide text-muted-foreground uppercase">
                    {where}
                  </div>
                  <ul className="grid gap-0.5">
                    {items.map((issue, i) => (
                      <li
                        className="flex items-start gap-1.5 text-[0.6875rem] leading-snug text-foreground"
                        data-severity={issue.severity}
                        key={`${where}-${i}`}
                      >
                        <span className={cn('shrink-0 font-medium', SEVERITY_CLASS[issue.severity])}>
                          {issue.severity === 'error' ? copy.error : copy.warn}
                        </span>
                        <span className="min-w-0">{issue.message}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-center gap-2">
            {issues.length > 0 && (
              <span title={sender ? undefined : copy.fixUnavailable}>
                <Button
                  className="h-6 px-2 text-[0.6875rem]"
                  disabled={!sender || sent}
                  onClick={() => void fix()}
                  size="sm"
                >
                  {sent ? copy.fixSent : copy.fix}
                </Button>
              </span>
            )}
            {checked?.vision && checked.model && (
              <span className="min-w-0 truncate text-[0.625rem] text-muted-foreground">
                {copy.checkedBy(checked.model)}
              </span>
            )}
            {checked && checkNote(checked, copy) && (
              <span className="min-w-0 truncate text-[0.625rem] text-muted-foreground">{checkNote(checked, copy)}</span>
            )}
            <button
              aria-label={copy.dismiss}
              className="ml-auto grid size-5 shrink-0 place-items-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={() => setState({ phase: 'idle' })}
              type="button"
            >
              <X className="size-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function checkNote(
  checked: DocCheckResult['checked'],
  copy: { noRender: string; visionBusy: string; visionPartial: string }
): string | null {
  if (checked.render === false) {
    return copy.noRender
  }

  if (checked.vision_busy) {
    return copy.visionBusy
  }

  return checked.vision_partial ? copy.visionPartial : null
}
