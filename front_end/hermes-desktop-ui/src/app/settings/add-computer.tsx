import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Loader2 } from '@/lib/icons'
import { confirm } from '@/store/confirm'
import { notify, notifyError } from '@/store/notifications'

import { fetchInferenceNodes, type InferenceNode, pairInferenceNode, removeInferenceNode } from './harvis-api'
import { ListRow, ListRowSkeleton, Pill } from './primitives'

export const nodesKey = ['harvis', 'settings', 'models', 'nodes'] as const

const PIN_LENGTH = 6

const modelCount = (n: number) => `${n} model${n === 1 ? '' : 's'}`

function NodeRow({ node }: { node: InferenceNode }) {
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const name = node.label || node.name

  const remove = async () => {
    const ok = await confirm({
      title: `Remove ${name}?`,
      description: 'Harvis stops using its models. You can add it again with a new PIN.',
      confirmLabel: 'Remove',
      destructive: true
    })

    if (!ok) {
      return
    }

    setBusy(true)

    try {
      await removeInferenceNode(node.name)
      await queryClient.invalidateQueries({ queryKey: nodesKey })
    } catch (err) {
      notifyError(err, 'Could not remove that computer')
    } finally {
      setBusy(false)
    }
  }

  return (
    <ListRow
      action={
        // Computers set up on the server itself are managed there, not from this page.
        node.source === 'db' ? (
          <Button disabled={busy} onClick={() => void remove()} size="sm" variant="outline">
            {busy && <Loader2 className="animate-spin" />}
            Remove
          </Button>
        ) : undefined
      }
      description={`${node.base_url} · ${modelCount((node.models ?? []).length)}`}
      key={node.name}
      title={
        <span className="flex flex-wrap items-center gap-2">
          {name}
          <Pill tone={node.reachable ? 'primary' : 'warn'}>{node.reachable ? 'Online' : 'Offline'}</Pill>
        </span>
      }
      wide
    />
  )
}

/** The pairing form: address plus the PIN the other computer is showing. */
export function AddComputerForm() {
  const queryClient = useQueryClient()
  const [address, setAddress] = useState('')
  const [pin, setPin] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<null | string>(null)

  const ready = address.trim().length > 0 && pin.length === PIN_LENGTH

  const submit = async () => {
    setBusy(true)
    setError(null)

    try {
      const { node } = await pairInferenceNode(address.trim(), pin, name.trim() || undefined)
      notify({ kind: 'success', title: 'Computer added', message: node.label || node.name })
      setAddress('')
      setPin('')
      setName('')
      await queryClient.invalidateQueries({ queryKey: nodesKey })
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'Could not add that computer.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="mt-3 grid max-w-[40rem] gap-3 rounded-md bg-(--ui-bg-tertiary)/50 p-3"
      onSubmit={e => {
        e.preventDefault()

        if (ready && !busy) {
          void submit()
        }
      }}
    >
      <div className="text-[0.8125rem] font-medium">Add a computer</div>
      <p className="text-[0.75rem] text-(--ui-text-tertiary)">
        On the other computer, run harvis_node.py. It shows a 6-digit PIN.
      </p>
      <label className="grid gap-1.5">
        <span className="text-[0.8125rem] font-medium">Address</span>
        <Input onChange={e => setAddress(e.target.value)} placeholder="192.168.1.50" value={address} />
      </label>
      <label className="grid gap-1.5">
        <span className="text-[0.8125rem] font-medium">PIN</span>
        <Input
          autoComplete="off"
          className="w-40 font-mono tracking-widest"
          inputMode="numeric"
          maxLength={PIN_LENGTH}
          onChange={e => setPin(e.target.value.replace(/\D/g, '').slice(0, PIN_LENGTH))}
          placeholder="123456"
          value={pin}
        />
      </label>
      <label className="grid gap-1.5">
        <span className="text-[0.8125rem] font-medium">Name (optional)</span>
        <Input onChange={e => setName(e.target.value)} placeholder="Gaming PC" value={name} />
      </label>
      {error && (
        <p className="text-[0.8125rem] text-destructive" role="alert">
          {error}
        </p>
      )}
      <div>
        <Button disabled={!ready || busy} type="submit">
          {busy && <Loader2 className="animate-spin" />}
          Add computer
        </Button>
      </div>
    </form>
  )
}

/** Admin only: the other computers whose models Harvis can use, and how to add one. */
export function OtherComputers() {
  const nodes = useQuery({ queryFn: () => fetchInferenceNodes(), queryKey: nodesKey })
  const rows = nodes.data ?? []

  return (
    <div>
      {nodes.isPending ? (
        <ListRowSkeleton wide />
      ) : nodes.isError ? (
        <p className="py-2 text-[0.8125rem] text-destructive" role="alert">
          {nodes.error instanceof Error ? nodes.error.message : 'Could not load the other computers.'}
        </p>
      ) : rows.length === 0 ? (
        <p className="py-2 text-[0.8125rem] text-(--ui-text-secondary)">No other computers yet.</p>
      ) : (
        <div className="divide-y">
          {rows.map(n => (
            <NodeRow key={n.name} node={n} />
          ))}
        </div>
      )}
      <AddComputerForm />
    </div>
  )
}
