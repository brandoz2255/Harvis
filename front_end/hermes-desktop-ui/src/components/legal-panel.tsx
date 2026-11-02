import { type KeyboardEvent, type ReactNode, useCallback, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { Button } from '@/components/ui/button'
import { fetchLegal, type Legal, type LegalSection } from '@/lib/legal'
import { Loader2, RefreshCw, X } from '@/lib/icons'

// A plain panel instead of the shared Radix dialog: the sign-in screen sits above
// every dialog layer (--z-setup), so a dialog opened from it would open behind it.
const FOCUSABLE = 'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'

function Sections({ items, title }: { items: LegalSection[]; title: string }) {
  if (!items.length) {
    return null
  }

  return (
    <section className="grid gap-3">
      <h3 className="text-[0.9375rem] font-semibold tracking-tight text-foreground">{title}</h3>
      <dl className="grid gap-3">
        {items.map(s => (
          <div className="grid gap-1" key={s.heading}>
            <dt className="text-[0.8125rem] font-medium text-foreground">{s.heading}</dt>
            <dd className="text-[0.8125rem] leading-5 text-(--ui-text-secondary)">{s.body}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function Body({ legal }: { legal: Legal }) {
  const { houseRules } = legal

  return (
    <>
      <Sections items={legal.terms} title="Terms of Use" />
      <Sections items={legal.acceptableUse} title="Acceptable Use" />
      {houseRules.required && (
        <section className="grid gap-3">
          <h3 className="text-[0.9375rem] font-semibold tracking-tight text-foreground">House rules</h3>
          <p className="text-[0.8125rem] leading-5 text-(--ui-text-tertiary)">
            The person who runs this Harvis asks everyone who signs up to agree to these.
          </p>
          <ul className="grid list-disc gap-1.5 pl-5 text-[0.8125rem] leading-5 text-(--ui-text-secondary)">
            {houseRules.points.map(point => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

// An older server has no /api/legal. Say what is always true of Harvis, and no more.
function Unavailable() {
  return (
    <p className="text-[0.8125rem] leading-5 text-(--ui-text-secondary)">
      This Harvis does not publish its terms yet. Harvis is open-source software under the MIT license and comes with no
      warranty; the license is the LICENSE file in its source. Whoever runs this Harvis sets its rules.
    </p>
  )
}

/** The Terms of Use, Acceptable Use and house rules. Mount it to open it; `onClose` unmounts it. */
export function LegalPanel({ onClose }: { onClose: () => void }) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const [legal, setLegal] = useState<Legal | null | undefined>(undefined)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let live = true
    setLegal(undefined)
    setFailed(false)

    fetchLegal()
      .then(next => live && setLegal(next))
      .catch(() => live && setFailed(true))

    return () => {
      live = false
    }
  }, [attempt])

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    panel.current?.querySelector<HTMLElement>('[data-legal-close]')?.focus()

    return () => opener?.focus?.()
  }, [])

  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()

        return
      }

      if (e.key !== 'Tab' || !panel.current) {
        return
      }

      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
      const first = items[0]
      const last = items[items.length - 1]

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last?.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first?.focus()
      }
    },
    [onClose]
  )

  let content: ReactNode

  if (failed) {
    content = (
      <div className="grid justify-items-start gap-3" role="alert">
        <p className="text-[0.8125rem] leading-5 text-(--ui-text-secondary)">
          Harvis could not load its terms. Check that it is running, then try again.
        </p>
        <Button onClick={() => setAttempt(n => n + 1)} size="sm" type="button" variant="secondary">
          <RefreshCw />
          Try again
        </Button>
      </div>
    )
  } else if (legal === undefined) {
    content = (
      <p className="flex items-center gap-2 text-[0.8125rem] text-(--ui-text-tertiary)" role="status">
        <Loader2 className="size-4 animate-spin" />
        Loading…
      </p>
    )
  } else if (legal === null) {
    content = <Unavailable />
  } else {
    content = <Body legal={legal} />
  }

  return createPortal(
    <div
      className="fixed inset-0 z-(--z-setup) grid place-items-center bg-black/30 p-4 backdrop-blur-[0.125rem]"
      onKeyDown={onKeyDown}
      onMouseDown={e => e.target === e.currentTarget && onClose()}
    >
      <div
        aria-labelledby={titleId}
        aria-modal="true"
        className="relative flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl border border-(--stroke-nous) bg-(--ui-chat-bubble-background) text-foreground shadow-nous"
        ref={panel}
        role="dialog"
      >
        <header className="grid gap-0.5 border-b border-(--ui-stroke-tertiary) py-3 pr-12 pl-5">
          <h2 className="text-[1.0625rem] font-semibold tracking-tight" id={titleId}>
            Terms and Acceptable Use
          </h2>
          {legal && <p className="text-[0.75rem] text-(--ui-text-tertiary)">Version {legal.version}</p>}
        </header>
        <Button
          aria-label="Close"
          className="absolute top-2.5 right-2.5 text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground"
          data-legal-close=""
          onClick={onClose}
          size="icon-xs"
          type="button"
          variant="ghost"
        >
          <X className="size-4" />
        </Button>
        <div className="grid min-h-0 gap-6 overflow-y-auto px-5 py-4" tabIndex={0}>
          {content}
        </div>
      </div>
    </div>,
    document.body
  )
}

/** A text link that opens the panel. */
export function LegalLink({ children = 'Terms and Acceptable Use' }: { children?: ReactNode }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button onClick={() => setOpen(true)} size="inline" type="button" variant="text">
        {children}
      </Button>
      {open && <LegalPanel onClose={() => setOpen(false)} />}
    </>
  )
}
