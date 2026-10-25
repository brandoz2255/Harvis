import { host } from '@hermes/plugin-sdk'
import { useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

import {
  approvePending,
  getLearningNode,
  getPending,
  type PendingSkill,
  rejectPending,
  setSkillEnabled
} from '@/api/skills'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

/**
 * Review a skill a model wrote before it can apply. A model never edits a skill:
 * it proposes, and the proposal waits in the backend (rest_skills.py
 * /skills/pending) until a person approves the exact text shown here. The panel
 * shows the whole description and body, every script in full and, for an update,
 * a line diff against what is stored. It flags risky patterns; it never rejects
 * for you.
 */

export interface RiskFlag {
  id: 'base64' | 'ignore-previous' | 'script' | 'shell-fetch' | 'url'
  label: string
}

const URL_RE = /\bhttps?:\/\/\S+/i
const FETCH_RE = /\b(?:curl|wget)\b/i
const IGNORE_RE = /\bignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding)\b/i
const BASE64_RE = /[A-Za-z0-9+/_-]{200,}={0,2}/

type Reviewable = Pick<PendingSkill, 'content' | 'description' | 'files'>

/** Patterns a person should look at twice. Pure, so the flags are the same in the panel and the tests. */
export function riskFlags(item: Reviewable): RiskFlag[] {
  const files = (item.files ?? []).filter(file => file.content != null)
  const text = [item.description, item.content, ...files.map(file => file.content as string)].join('\n')
  const flags: RiskFlag[] = []

  if (URL_RE.test(text)) {
    flags.push({ id: 'url', label: 'Contains a URL' })
  }

  if (FETCH_RE.test(text)) {
    flags.push({ id: 'shell-fetch', label: 'Mentions curl or wget' })
  }

  if (IGNORE_RE.test(text)) {
    flags.push({ id: 'ignore-previous', label: 'Tells the model to ignore earlier instructions' })
  }

  if (BASE64_RE.test(text)) {
    flags.push({ id: 'base64', label: 'Contains a long encoded blob (200+ characters)' })
  }

  if (files.length > 0) {
    flags.push({ id: 'script', label: files.length === 1 ? 'Includes a script file' : `Includes ${files.length} script files` })
  }

  return flags
}

function DiffView({ diff }: { diff: string }) {
  const lines = diff.split('\n')

  return (
    <pre className="max-h-64 overflow-auto rounded-md bg-(--ui-bg-quaternary) p-2 font-mono text-xs leading-5" data-testid="skill-diff">
      {lines.map((line, i) => {
        const tone =
          line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@')
            ? 'text-muted-foreground'
            : line.startsWith('+')
              ? 'text-emerald-600 dark:text-emerald-300'
              : line.startsWith('-')
                ? 'text-destructive'
                : ''

        return (
          <div className={`whitespace-pre-wrap break-words ${tone}`} key={i}>
            {line || ' '}
          </div>
        )
      })}
    </pre>
  )
}

function Block({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <section className="grid gap-1.5">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  )
}

function Text({ text }: { text: string }) {
  return (
    <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-(--ui-bg-quaternary) p-2 font-mono text-xs leading-5">
      {text}
    </pre>
  )
}

type Load =
  | { kind: 'error'; message: string }
  | { kind: 'legacy'; body: string }
  | { kind: 'loading' }
  | { item: PendingSkill; kind: 'pending' }

/**
 * The sentence in an API error. The desktop shim throws `409 Conflict: {"detail":"..."}`
 * (lib/desktop-shim/api.ts), which is not something to show a person: take the FastAPI `detail`
 * out of it, or the text after the status when the body isn't JSON.
 */
export function messageOf(err: unknown, fallback: string): string {
  const raw = err instanceof Error ? err.message.trim() : ''

  if (!raw) {
    return fallback
  }

  const body = raw.replace(/^\d{3}[^:{]*:\s*/, '')

  try {
    const detail = (JSON.parse(body) as { detail?: unknown } | null)?.detail

    if (typeof detail === 'string' && detail.trim()) {
      return detail.trim()
    }
  } catch {
    // Not JSON: the text itself is the message.
  }

  return body || fallback
}

export interface SkillReviewResult {
  approved: boolean
  name: string
}

export interface SkillReviewDialogProps {
  name: string
  onClose: () => void
  /** Called once the person approved or rejected (the dialog closes itself next). */
  onResolved?: (result: SkillReviewResult) => void
}

export function SkillReviewDialog({ name, onClose, onResolved }: SkillReviewDialogProps) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' })
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')

  const fetchItem = useCallback(async () => {
    try {
      const { items } = await getPending()
      const item = (items ?? []).find(entry => entry.name === name)

      if (item) {
        setLoad({ item, kind: 'pending' })

        return
      }

      // Not waiting as a proposal: a draft saved earlier (off, never approved). Still show the
      // whole text before it can be switched on.
      const node = await getLearningNode(name)
      setLoad({ body: node.content ?? '', kind: 'legacy' })
    } catch (err) {
      setLoad({ kind: 'error', message: messageOf(err, `Couldn't load ${name}.`) })
    }
  }, [name])

  useEffect(() => {
    void fetchItem()
  }, [fetchItem])

  const finish = (approved: boolean, message: string) => {
    host.notify({ id: `harvis-skill-${name}`, kind: 'success', message })
    onResolved?.({ approved, name })
    onClose()
  }

  const approve = async () => {
    setBusy(true)
    setProblem('')

    try {
      if (load.kind === 'pending') {
        const res = await approvePending(name, load.item.pending_sha)

        if (!res.ok) {
          throw new Error(`Couldn't approve ${name}.`)
        }

        // The backend's message always says Harvis will use it; only trust it when the skill is on.
        finish(
          true,
          res.enabled === false
            ? `Approved ${name}, but it is still switched off. Turn it on in the Skills tab for Harvis to use it.`
            : res.message || `Approved ${name}. Harvis will use this version.`
        )
      } else {
        const res = await setSkillEnabled(name, true)

        if (!res.ok) {
          throw new Error(`Couldn't enable ${name}.`)
        }

        finish(true, `${name} is on. Harvis will use it when a chat matches.`)
      }
    } catch (err) {
      // A 409 means the proposal changed since it was opened: reload so the person reads the new text.
      setProblem(messageOf(err, `Couldn't approve ${name}.`))
      void fetchItem()
    } finally {
      setBusy(false)
    }
  }

  const reject = async () => {
    setBusy(true)
    setProblem('')

    try {
      const res = await rejectPending(name)

      if (!res.ok) {
        throw new Error(`Couldn't reject ${name}.`)
      }

      finish(false, res.message || `Rejected the proposal for ${name}.`)
    } catch (err) {
      setProblem(messageOf(err, `Couldn't reject ${name}.`))
    } finally {
      setBusy(false)
    }
  }

  const item = load.kind === 'pending' ? load.item : null
  const flags = item ? riskFlags(item) : load.kind === 'legacy' ? riskFlags({ content: load.body, description: '', files: [] }) : []

  return (
    <Dialog onOpenChange={open => !open && onClose()} open>
      <DialogContent className="max-w-2xl" data-testid="skill-review">
        <DialogHeader>
          <DialogTitle>{item ? (item.is_new ? `New skill: ${name}` : `Update to ${name}`) : `Review ${name}`}</DialogTitle>
          <DialogDescription>
            Nothing changes until you approve. Read the whole text first: a model wrote it, and it may carry text copied
            from a web page or tool output.
          </DialogDescription>
        </DialogHeader>

        {load.kind === 'loading' && <p className="text-sm text-muted-foreground">Loading…</p>}
        {load.kind === 'error' && (
          <p className="text-sm text-destructive" role="alert">
            {load.message}
          </p>
        )}

        {flags.length > 0 && (
          <div className="grid gap-1 rounded-md border border-amber-500/40 bg-amber-500/5 p-2" data-testid="skill-risk-flags" role="note">
            <div className="text-xs font-semibold">Look closely: this draft has</div>
            <ul className="flex flex-wrap gap-1">
              {flags.map(flag => (
                <li key={flag.id}>
                  <Badge data-flag={flag.id} variant="warn">
                    {flag.label}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        )}

        {item && !item.is_new && !item.enabled && (
          <p className="text-xs text-amber-600 dark:text-amber-300" data-testid="skill-off-note" role="note">
            This skill is switched off right now. Approving a draft nobody approved before turns it on; a skill you
            switched off yourself stays off.
          </p>
        )}

        {item?.stale && (
          <p className="text-xs text-amber-600 dark:text-amber-300" role="note">
            The saved skill changed after this was proposed, so the diff below may not line up with what you remember.
          </p>
        )}

        {item && (
          <>
            <Block title="Description">
              <Text text={item.description || '(none)'} />
            </Block>
            <Block title="Full text">
              <Text text={item.content} />
            </Block>
            {!item.is_new && (
              <Block title="Changes from the current text">
                {item.diff ? <DiffView diff={item.diff} /> : <p className="text-xs text-muted-foreground">No change to the text.</p>}
              </Block>
            )}
            {item.files.map(file => (
              <Block key={file.path} title={`Script: ${file.path} (${file.status})`}>
                {file.content == null ? (
                  <p className="text-xs text-muted-foreground">This proposal removes the file.</p>
                ) : (
                  <Text text={file.content} />
                )}
                {file.status === 'changed' && file.diff && <DiffView diff={file.diff} />}
              </Block>
            ))}
            {item.files.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Scripts are copied into the chat sandbox for the model to run there. Harvis itself never runs them.
              </p>
            )}
          </>
        )}

        {load.kind === 'legacy' && (
          <Block title="Full text (saved draft, switched off)">
            <Text text={load.body} />
          </Block>
        )}

        {problem && (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <Button disabled={busy} onClick={onClose} variant="ghost">
            Close
          </Button>
          {load.kind === 'pending' && (
            <Button disabled={busy} onClick={() => void reject()} variant="outline">
              Reject
            </Button>
          )}
          <Button disabled={busy || (load.kind !== 'pending' && load.kind !== 'legacy')} onClick={() => void approve()}>
            {load.kind === 'legacy' ? 'Enable' : 'Approve'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

const open = new Set<string>()

/**
 * Open the review panel for `name` in its own React root on document.body, so a toast can
 * launch it without the plugin registering a surface for it. One panel per skill at a time.
 * Returns a function that closes it.
 */
export function openSkillReview(name: string, onResolved?: (result: SkillReviewResult) => void): () => void {
  if (open.has(name)) {
    return () => undefined
  }

  open.add(name)

  const container = document.createElement('div')
  container.dataset.skillReview = name
  document.body.append(container)

  const root = createRoot(container)
  let closed = false

  const close = () => {
    if (closed) {
      return
    }

    closed = true
    open.delete(name)
    // Unmount after the current event so Radix finishes its own close handlers first.
    queueMicrotask(() => {
      root.unmount()
      container.remove()
    })
  }

  root.render(<SkillReviewDialog name={name} onClose={close} onResolved={onResolved} />)

  return close
}
