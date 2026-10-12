/** A mind map as a collapsible outline: the topic at the top, branches that open and close. */

import { Button, Codicon } from '@hermes/plugin-sdk'
import { useState } from 'react'

import type { MindNode, MindTree } from './notebook-artifacts'

type Mode = 'all' | 'first' | 'none'

function Branch({ depth, mode, node }: { depth: number; mode: Mode; node: MindNode }) {
  const kids = node.children ?? []
  const [open, setOpen] = useState(mode === 'all' || (mode === 'first' && depth < 1))

  if (kids.length === 0) {
    return (
      <li className="flex items-start gap-1.5 py-0.5 text-xs">
        <span className="mt-1.5 size-1 shrink-0 rounded-full bg-(--ui-text-tertiary)" />
        <span>{node.label}</span>
      </li>
    )
  }

  return (
    <li className="py-0.5">
      <button
        aria-expanded={open}
        className="flex items-start gap-1 text-left text-xs font-medium hover:text-foreground"
        onClick={() => setOpen(o => !o)}
        type="button"
      >
        <Codicon className="mt-0.5 shrink-0" name={open ? 'chevron-down' : 'chevron-right'} size="0.75rem" />
        <span>{node.label}</span>
        <span className="font-normal text-(--ui-text-tertiary)">{kids.length}</span>
      </button>
      {open && (
        <ul className="ml-2 border-l pl-3">
          {kids.map((kid, i) => (
            <Branch depth={depth + 1} key={i} mode={mode} node={kid} />
          ))}
        </ul>
      )}
    </li>
  )
}

export function MindMap({ tree }: { tree: MindTree }) {
  const [version, setVersion] = useState<{ mode: Mode; n: number }>({ mode: 'first', n: 0 })

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <h5 className="flex-1 text-sm font-semibold">{tree.title}</h5>
        <Button onClick={() => setVersion(v => ({ mode: 'all', n: v.n + 1 }))} size="xs" variant="ghost">
          Expand all
        </Button>
        <Button onClick={() => setVersion(v => ({ mode: 'none', n: v.n + 1 }))} size="xs" variant="ghost">
          Collapse all
        </Button>
      </div>
      <ul key={version.n}>
        {(tree.children ?? []).map((node, i) => (
          <Branch depth={0} key={i} mode={version.mode} node={node} />
        ))}
      </ul>
    </div>
  )
}
