import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Loader2 } from '@/lib/icons'
import { notify, notifyError } from '@/store/notifications'

import {
  approveRequest,
  denyRequest,
  fetchMyRequests,
  fetchOpenRequests,
  type ModelRequest,
  type ModelRequestStatus,
  requestModel
} from './harvis-api'
import { ListRow, ListRowSkeleton, Pill } from './primitives'

export const myRequestsKey = ['harvis', 'settings', 'models', 'requests', 'mine'] as const
export const openRequestsKey = ['harvis', 'settings', 'models', 'requests', 'open'] as const

const STATUS_LABEL: Record<ModelRequestStatus, string> = {
  approved: 'Approved',
  denied: 'Denied',
  open: 'Waiting'
}

const STATUS_TONE = { approved: 'primary', denied: 'warn', open: 'muted' } as const

const errorText = (err: unknown, fallback: string) => (err instanceof Error && err.message ? err.message : fallback)

const votesLabel = (votes: number) => (votes === 1 ? '1 person asked' : `${votes} people asked`)

/** Non-admins: ask the admin for a model. The server's own sentence is shown as-is, spam limit included. */
export function RequestModelForm() {
  const queryClient = useQueryClient()
  const [model, setModel] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<null | string>(null)
  const [done, setDone] = useState<null | string>(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    setDone(null)

    try {
      const { joined } = await requestModel(model.trim(), note.trim() || undefined)
      setDone(
        joined ? 'Someone already asked for that one. Your vote is added.' : 'Request sent. The admin will see it.'
      )
      setModel('')
      setNote('')
      await queryClient.invalidateQueries({ queryKey: myRequestsKey })
    } catch (err) {
      setError(errorText(err, 'Could not send the request.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="grid max-w-[40rem] gap-3"
      onSubmit={e => {
        e.preventDefault()

        if (model.trim() && !busy) {
          void submit()
        }
      }}
    >
      <label className="grid gap-1.5">
        <span className="text-[0.8125rem] font-medium">Model</span>
        <Input onChange={e => setModel(e.target.value)} placeholder="gemma3:4b" value={model} />
      </label>
      <label className="grid gap-1.5">
        <span className="text-[0.8125rem] font-medium">Why you want it (optional)</span>
        <Input onChange={e => setNote(e.target.value)} placeholder="Better at writing code" value={note} />
      </label>
      {error && (
        <p className="text-[0.8125rem] text-destructive" role="alert">
          {error}
        </p>
      )}
      {done && (
        <p className="text-[0.8125rem] text-(--ui-text-secondary)" role="status">
          {done}
        </p>
      )}
      <div>
        <Button disabled={!model.trim() || busy} type="submit">
          {busy && <Loader2 className="animate-spin" />}
          Request model
        </Button>
      </div>
    </form>
  )
}

export function MyRequests() {
  const mine = useQuery({ queryFn: fetchMyRequests, queryKey: myRequestsKey })
  const rows = mine.data?.requests ?? []

  if (mine.isPending) {
    return <ListRowSkeleton wide />
  }

  if (mine.isError) {
    return (
      <p className="py-2 text-[0.8125rem] text-destructive" role="alert">
        {errorText(mine.error, 'Could not load your requests.')}
      </p>
    )
  }

  if (rows.length === 0) {
    return <p className="py-2 text-[0.8125rem] text-(--ui-text-secondary)">You have not asked for any models yet.</p>
  }

  return (
    <div className="divide-y">
      {rows.map(r => (
        <ListRow
          description={
            r.status === 'denied' && r.reason ? `Reason: ${r.reason}` : r.status === 'open' ? votesLabel(r.votes) : ''
          }
          key={r.id}
          title={
            <span className="flex flex-wrap items-center gap-2">
              <span className="break-all">{r.model}</span>
              <Pill tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</Pill>
            </span>
          }
          wide
        />
      ))}
    </div>
  )
}

function OpenRequestRow({ onApprove, request }: { onApprove: (model: string) => void; request: ModelRequest }) {
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [denying, setDenying] = useState(false)
  const [reason, setReason] = useState('')

  const refresh = () => queryClient.invalidateQueries({ queryKey: openRequestsKey })

  const approve = async () => {
    setBusy(true)

    try {
      await approveRequest(request.id)
      await refresh()
      // Approving is a promise to get the model: start the download now.
      onApprove(request.model)
    } catch (err) {
      notifyError(err, 'Could not approve that request')
      // Another admin may have answered it first; drop the stale row.
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  const deny = async () => {
    setBusy(true)

    try {
      await denyRequest(request.id, reason.trim() || undefined)
      await refresh()
      notify({ kind: 'success', title: 'Request denied', message: request.model })
    } catch (err) {
      notifyError(err, 'Could not deny that request')
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <ListRow
      action={
        <div className="flex flex-wrap items-center gap-2 @2xl:justify-end">
          <Button disabled={busy} onClick={() => void approve()} size="sm">
            {busy && <Loader2 className="animate-spin" />}
            Approve and download
          </Button>
          <Button disabled={busy} onClick={() => setDenying(d => !d)} size="sm" variant="outline">
            Deny
          </Button>
        </div>
      }
      below={
        denying && (
          <div className="mt-2 flex max-w-[32rem] gap-2">
            <Input
              aria-label="Reason for denying"
              onChange={e => setReason(e.target.value)}
              placeholder="Reason (optional)"
              value={reason}
            />
            <Button disabled={busy} onClick={() => void deny()} size="sm" variant="destructive">
              Deny request
            </Button>
          </div>
        )
      }
      description={
        <>
          {votesLabel(request.votes)}, first by {request.requested_by.username || 'someone'}
          {request.note ? `. "${request.note}"` : ''}
        </>
      }
      key={request.id}
      title={<span className="break-all">{request.model}</span>}
    />
  )
}

/** Admins: what people have asked for. Approving also starts the download. */
export function OpenRequests({ onApprove }: { onApprove: (model: string) => void }) {
  const open = useQuery({ queryFn: fetchOpenRequests, queryKey: openRequestsKey })
  const rows = open.data?.requests ?? []

  if (open.isPending) {
    return <ListRowSkeleton wide />
  }

  if (open.isError) {
    return (
      <p className="py-2 text-[0.8125rem] text-destructive" role="alert">
        {errorText(open.error, 'Could not load requests.')}
      </p>
    )
  }

  if (rows.length === 0) {
    return <p className="py-2 text-[0.8125rem] text-(--ui-text-secondary)">No one is waiting on a model.</p>
  }

  return (
    <div className="divide-y">
      {[...rows]
        .sort((a, b) => b.votes - a.votes)
        .map(r => (
          <OpenRequestRow key={r.id} onApprove={onApprove} request={r} />
        ))}
    </div>
  )
}
