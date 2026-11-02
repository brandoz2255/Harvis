/**
 * Notebook sharing. The owner gives an existing account a role (by username or email) or makes a link code;
 * anyone with a code redeems it while signed in. There is no anonymous access, and a link only joins people:
 * each person who joined holds their own share, which is revoked on its own row.
 *
 * Backend: `python_back_end/notebooks/router_shares.py`.
 */

import {
  Button,
  Codicon,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  SegmentedControl,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useState } from 'react'

import { harvisApi } from './api'
import { errorText } from './notebook-shared'

export type ShareRole = 'chat_only' | 'editor' | 'viewer'

export interface NotebookShare {
  created_at: null | string
  id: string
  kind: 'link' | 'user'
  role: ShareRole
  /** Only present in the response that created a link; the server keeps a hash and never shows it again. */
  token?: string
  username: null | string
}

const ROLES: { hint: string; id: ShareRole; label: string }[] = [
  { hint: 'Reads sources, notes and studio items. Cannot chat or change anything.', id: 'viewer', label: 'Viewer' },
  {
    hint: 'Chats with their own private history. Never sees source text or notes.',
    id: 'chat_only',
    label: 'Chat only'
  },
  {
    hint: 'Reads, chats, and adds or removes sources and notes. Cannot share or delete.',
    id: 'editor',
    label: 'Editor'
  }
]

export const roleLabel = (role: string) => ROLES.find(r => r.id === role)?.label ?? role

const base = (notebookId: string) => `/api/notebooks/${encodeURIComponent(notebookId)}`

export const sharesKey = (notebookId: string) => ['harvis', 'notebooks', notebookId, 'shares'] as const

export const fetchShares = (notebookId: string) =>
  harvisApi<{ shares: NotebookShare[] }>(`${base(notebookId)}/shares`).then(r => r.shares)

export const addUserShare = (notebookId: string, user: string, role: ShareRole) =>
  harvisApi<NotebookShare>(`${base(notebookId)}/shares`, {
    body: JSON.stringify({ role, user: user.trim() }),
    method: 'POST'
  })

export const createLinkShare = (notebookId: string, role: ShareRole) =>
  harvisApi<NotebookShare>(`${base(notebookId)}/shares/link`, { body: JSON.stringify({ role }), method: 'POST' })

export const revokeShare = (notebookId: string, shareId: string) =>
  harvisApi<{ message: string }>(`${base(notebookId)}/shares/${encodeURIComponent(shareId)}`, { method: 'DELETE' })

export const acceptLink = (token: string) =>
  harvisApi<{ notebook_id: string; role: string }>('/api/notebooks/shares/accept', {
    body: JSON.stringify({ token: token.trim() }),
    method: 'POST'
  })

function RolePicker({ onChange, value }: { onChange: (role: ShareRole) => void; value: ShareRole }) {
  return (
    <div className="space-y-1">
      <SegmentedControl onChange={onChange} options={ROLES} value={value} />
      <p className="text-xs text-(--ui-text-tertiary)">{ROLES.find(r => r.id === value)?.hint}</p>
    </div>
  )
}

export function NotebookShareButton({ isOwner, notebookId }: { isOwner: boolean; notebookId: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [who, setWho] = useState('')
  const [role, setRole] = useState<ShareRole>('viewer')
  const [linkRole, setLinkRole] = useState<ShareRole>('viewer')
  const [code, setCode] = useState('')
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const shares = useQuery({
    enabled: open && isOwner,
    queryFn: () => fetchShares(notebookId),
    queryKey: sharesKey(notebookId),
    retry: false,
    staleTime: 0
  })

  if (!isOwner) {
    return null
  }

  const run = async (work: () => Promise<void>) => {
    setBusy(true)
    setError('')

    try {
      await work()
      await queryClient.invalidateQueries({ queryKey: sharesKey(notebookId) })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const add = () =>
    run(async () => {
      await addUserShare(notebookId, who, role)
      setWho('')
    })

  const makeLink = () =>
    run(async () => {
      const made = await createLinkShare(notebookId, linkRole)
      setCode(made.token ?? '')
      setCopied(false)
    })

  const revoke = (share: NotebookShare) =>
    run(async () => {
      await revokeShare(notebookId, share.id)

      if (share.kind === 'link') {
        setCode('')
      }
    })

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
    } catch {
      setError('Copy did not work. Select the code and copy it by hand.')
    }
  }

  const list = shares.data ?? []

  return (
    <>
      <Button
        aria-label="Share notebook"
        onClick={() => setOpen(true)}
        size="sm"
        title="Share notebook"
        variant="ghost"
      >
        <Codicon name="live-share" size="0.8rem" />
      </Button>
      <Dialog onOpenChange={next => !busy && setOpen(next)} open={open}>
        <DialogContent bodyClassName="flex flex-col gap-3 p-4" className="max-w-md">
          <DialogHeader>
            <DialogTitle>Share notebook</DialogTitle>
            <DialogDescription>
              People need an account here and must sign in. Chat history stays private to each person.
            </DialogDescription>
          </DialogHeader>

          <section className="space-y-1.5">
            <label className="text-xs font-medium" htmlFor="share-who">
              Add a person
            </label>
            <div className="flex gap-1.5">
              <Input
                id="share-who"
                onChange={e => setWho(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && who.trim() && !busy && void add()}
                placeholder="Username or email"
                value={who}
              />
              <Button disabled={busy || !who.trim()} onClick={() => void add()} size="sm">
                Add
              </Button>
            </div>
            <RolePicker onChange={setRole} value={role} />
          </section>

          <section className="space-y-1.5">
            <p className="text-xs font-medium">Link code</p>
            <RolePicker onChange={setLinkRole} value={linkRole} />
            <Button disabled={busy} onClick={() => void makeLink()} size="sm" variant="outline">
              Create link code
            </Button>
            {code && (
              <div className="space-y-1">
                <div className="flex gap-1.5">
                  <Input aria-label="Link code" onFocus={e => e.currentTarget.select()} readOnly value={code} />
                  <Button onClick={() => void copy()} size="sm" variant="outline">
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                </div>
                <p className="text-xs text-(--ui-text-tertiary)">
                  Shown once. Send it to people who have an account; they enter it under Join a notebook.
                </p>
              </div>
            )}
          </section>

          <section className="space-y-1">
            <p className="text-xs font-medium">Who has access</p>
            {shares.isLoading ? (
              <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
            ) : shares.error ? (
              <p className="text-xs text-destructive">{errorText(shares.error)}</p>
            ) : list.length === 0 ? (
              <p className="text-xs text-(--ui-text-tertiary)">Only you.</p>
            ) : (
              <ul className="space-y-1">
                {list.map(share => {
                  const name = share.kind === 'link' ? 'Link code' : (share.username ?? 'Unknown account')

                  return (
                    <li className="flex items-center justify-between gap-2 text-sm" key={share.id}>
                      <span className="truncate">
                        {name} <span className="text-xs text-(--ui-text-tertiary)">{roleLabel(share.role)}</span>
                      </span>
                      <Button
                        aria-label={`Revoke ${name}`}
                        disabled={busy}
                        onClick={() => void revoke(share)}
                        size="sm"
                        variant="ghost"
                      >
                        Revoke
                      </Button>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>

          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button onClick={() => setOpen(false)} size="sm" variant="ghost">
              Done
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

/** Redeem a link code as the signed-in person. For the notebook list page; `onJoined` gets the notebook id. */
export function NotebookJoinButton({ onJoined }: { onJoined?: (notebookId: string) => void }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const join = async () => {
    setBusy(true)
    setError('')

    try {
      const joined = await acceptLink(code)
      await queryClient.invalidateQueries({ queryKey: ['harvis', 'notebooks'] })
      setOpen(false)
      setCode('')
      onJoined?.(joined.notebook_id)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button onClick={() => setOpen(true)} size="sm" variant="outline">
        Join a notebook
      </Button>
      <Dialog onOpenChange={next => !busy && setOpen(next)} open={open}>
        <DialogContent bodyClassName="flex flex-col gap-3 p-4" className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Join a notebook</DialogTitle>
            <DialogDescription>Enter the link code the owner sent you.</DialogDescription>
          </DialogHeader>
          <Input
            aria-label="Link code"
            onChange={e => setCode(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && code.trim() && !busy && void join()}
            placeholder="Link code"
            value={code}
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-1.5">
            <Button disabled={busy} onClick={() => setOpen(false)} size="sm" variant="ghost">
              Cancel
            </Button>
            <Button disabled={busy || !code.trim()} onClick={() => void join()} size="sm">
              {busy ? 'Joining…' : 'Join'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
