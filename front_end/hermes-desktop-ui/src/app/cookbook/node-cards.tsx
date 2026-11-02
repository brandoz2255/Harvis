import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Loader2 } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { confirm } from '@/store/confirm'
import { notify, notifyError } from '@/store/notifications'

import { addCookbookNode, type CookbookNode, type CookbookSystem, removeCookbookNode } from '../settings/harvis-api'
import { Pill } from '../settings/primitives'

export const nodesKey = ['harvis', 'cookbook', 'nodes'] as const
export const systemKey = (node: string) => ['harvis', 'cookbook', 'system', node] as const

const round = (n: number) => Math.round(n * 10) / 10

/** What llmfit found, as short lines. A missing field is left out, never guessed. */
export function hardwareRows(system: CookbookSystem): { label: string; value: string }[] {
  const rows: { label: string; value: string }[] = []

  rows.push({
    label: 'Graphics',
    value: system.gpu_name
      ? [system.gpu_name, system.gpu_vram_gb ? `${round(system.gpu_vram_gb)} GB video memory` : '']
          .filter(Boolean)
          .join(' · ')
      : 'No graphics card found'
  })

  if (system.total_ram_gb) {
    rows.push({ label: 'Memory', value: `${round(system.total_ram_gb)} GB` })
  }

  const cpu = [system.cpu_name, system.cpu_cores ? `${system.cpu_cores} cores` : ''].filter(Boolean).join(' · ')

  if (cpu) {
    rows.push({ label: 'Processor', value: cpu })
  }

  if (system.backend) {
    rows.push({ label: 'Runs on', value: system.backend })
  }

  return rows
}

function Hardware({ error, loading, system }: { error?: string; loading: boolean; system?: CookbookSystem }) {
  if (loading) {
    return <p className="mt-2 text-[0.75rem] text-(--ui-text-tertiary)">Reading the hardware…</p>
  }

  if (error || !system) {
    return (
      <p className="mt-2 text-[0.75rem] text-(--ui-text-secondary)">
        Could not read this computer&apos;s hardware.{error ? ` ${error}` : ''}
      </p>
    )
  }

  return (
    <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[0.75rem]">
      {hardwareRows(system).map(row => (
        <div className="contents" key={row.label}>
          <dt className="text-(--ui-text-tertiary)">{row.label}</dt>
          <dd className="min-w-0 break-words text-(--ui-text-secondary)">{row.value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** One computer: its name, whether llmfit answers, its hardware. Pick it to see its models. */
export function NodeCard({
  admin,
  node,
  onSelect,
  selected,
  system
}: {
  admin: boolean
  node: CookbookNode
  onSelect: () => void
  selected: boolean
  system: { error?: string; loading: boolean; value?: CookbookSystem }
}) {
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  // Nodes from the server's config refuse removal. Older servers do not send
  // `builtin`, so fall back to the one built-in we can recognise.
  const removable = admin && !(node.builtin ?? node.role === 'main')

  const remove = async () => {
    const ok = await confirm({
      title: `Remove ${node.name}?`,
      description: 'Harvis stops listing its models and hardware. You can add it again later.',
      confirmLabel: 'Remove',
      destructive: true
    })

    if (!ok) {
      return
    }

    setBusy(true)

    try {
      await removeCookbookNode(node.name)
      await queryClient.invalidateQueries({ queryKey: nodesKey })
    } catch (err) {
      notifyError(err, 'Could not remove that computer')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className={cn(
        'rounded-lg border p-3 transition-colors',
        selected ? 'border-primary/60 bg-(--ui-bg-tertiary)/50' : 'border-(--ui-stroke-tertiary)'
      )}
      data-testid={`cookbook-node-${node.name}`}
    >
      <button aria-pressed={selected} className="block w-full min-w-0 text-left" onClick={onSelect} type="button">
        <span className="flex flex-wrap items-center gap-2 text-[0.8125rem] font-medium">
          <span className="break-all">{node.name}</span>
          <Pill tone={node.alive ? 'primary' : 'warn'}>{node.alive ? 'Online' : 'Offline'}</Pill>
          {node.role === 'main' && <Pill>This server</Pill>}
        </span>
        {node.alive ? (
          <Hardware error={system.error} loading={system.loading} system={system.value} />
        ) : (
          <span className="mt-2 block text-[0.75rem] text-(--ui-text-secondary)">
            llmfit is not answering on this computer.
          </span>
        )}
      </button>
      {admin && node.llmfit_url && (
        <p className="mt-2 break-all font-mono text-[0.68rem] text-muted-foreground/60">{node.llmfit_url}</p>
      )}
      {removable && (
        <div className="mt-2">
          <Button disabled={busy} onClick={() => void remove()} size="sm" variant="outline">
            {busy && <Loader2 className="animate-spin" />}
            Remove
          </Button>
        </div>
      )}
    </div>
  )
}

/** Admin only. The server checks that llmfit answers at the address before it saves the computer. */
export function AddNodeForm({ onClose, onAdded }: { onAdded: (name: string) => void; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [llmfit, setLlmfit] = useState('')
  const [ollama, setOllama] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<null | string>(null)

  const ready = name.trim().length > 0 && llmfit.trim().length > 0

  const submit = async () => {
    setBusy(true)
    setError(null)

    try {
      const node = await addCookbookNode({
        name: name.trim(),
        llmfit_url: llmfit.trim(),
        ...(ollama.trim() ? { ollama_url: ollama.trim() } : {})
      })

      notify({ kind: 'success', title: 'Computer added', message: node.name })
      await queryClient.invalidateQueries({ queryKey: nodesKey })
      onAdded(node.name)
      onClose()
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'Could not add that computer.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="mb-4 grid max-w-[40rem] gap-3 rounded-md bg-(--ui-bg-tertiary)/50 p-3"
      onSubmit={e => {
        e.preventDefault()

        if (ready && !busy) {
          void submit()
        }
      }}
    >
      <div className="text-[0.8125rem] font-medium">Add a computer</div>
      <p className="text-[0.75rem] text-(--ui-text-tertiary)">
        On that computer, run <code>llmfit serve --host 0.0.0.0 --port 8787</code>. Harvis checks that it answers before
        it saves anything.
      </p>
      <label className="grid gap-1.5">
        <span className="text-[0.8125rem] font-medium">Name</span>
        <Input onChange={e => setName(e.target.value)} placeholder="Gaming PC" value={name} />
      </label>
      <label className="grid gap-1.5">
        <span className="text-[0.8125rem] font-medium">llmfit address</span>
        <Input onChange={e => setLlmfit(e.target.value)} placeholder="http://gaming-pc.local:8787" value={llmfit} />
      </label>
      <label className="grid gap-1.5">
        <span className="text-[0.8125rem] font-medium">Ollama address (optional)</span>
        <Input onChange={e => setOllama(e.target.value)} placeholder="http://gaming-pc.local:11434" value={ollama} />
        <span className="text-[0.75rem] text-(--ui-text-tertiary)">
          Without it, Harvis can show what fits but cannot download models onto that computer.
        </span>
      </label>
      {error && (
        <p className="text-[0.8125rem] text-destructive" role="alert">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button disabled={!ready || busy} type="submit">
          {busy && <Loader2 className="animate-spin" />}
          Add computer
        </Button>
        <Button onClick={onClose} type="button" variant="text">
          Cancel
        </Button>
      </div>
    </form>
  )
}
