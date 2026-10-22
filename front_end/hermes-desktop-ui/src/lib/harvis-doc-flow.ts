/** The flow (box diagram) and csv blocks. Tolerant like the rest of harvis-doc-blocks: never throws. */

import { bodyLines } from './harvis-doc-blocks'

// ─── flow ───────────────────────────────────────────────────────────────

export interface FlowNode {
  id: string
  /** 0-based column: the longest path from a source. */
  layer: number
  /** 0-based position within its column, in order of first appearance. */
  row: number
}

export interface FlowEdge {
  /** A cycle's closing edge: still drawn, but ignored for layering. */
  back: boolean
  from: string
  to: string
}

export interface Flow {
  edges: FlowEdge[]
  layers: number
  nodes: FlowNode[]
}

const ARROW_RE = /\s*(?:-+>|=>|→|⟶)\s*/

export function parseFlow(code: string): Flow {
  const order: string[] = []
  const edges: FlowEdge[] = []
  const known = new Set<string>()
  const seen = new Set<string>()

  const add = (id: string) => {
    if (!known.has(id)) {
      known.add(id)
      order.push(id)
    }
  }

  for (const line of bodyLines(code)) {
    const chain = line
      .split(ARROW_RE)
      .map(s => s.trim())
      .filter(Boolean)

    chain.forEach(add)
    chain.slice(1).forEach((to, i) => {
      const from = chain[i]
      const key = `${from}\u0000${to}`

      if (from !== to && !seen.has(key)) {
        seen.add(key)
        edges.push({ back: false, from, to })
      }
    })
  }

  const out = new Map<string, FlowEdge[]>()

  for (const edge of edges) {
    const list = out.get(edge.from)

    list ? list.push(edge) : out.set(edge.from, [edge])
  }

  // Depth-first, sources first and then the rest in order of appearance: an
  // edge into a node still on the stack closes a cycle. Iterative, so a long
  // chain cannot overflow the call stack.
  const state = new Map<string, 1 | 2>()
  const hasIncoming = new Set(edges.map(edge => edge.to))

  for (const root of [...order.filter(id => !hasIncoming.has(id)), ...order]) {
    if (state.has(root)) {
      continue
    }

    const stack: { id: string; next: number }[] = [{ id: root, next: 0 }]

    state.set(root, 1)

    while (stack.length) {
      const top = stack[stack.length - 1]
      const edge = out.get(top.id)?.[top.next++]

      if (!edge) {
        state.set(top.id, 2)
        stack.pop()
      } else if (state.get(edge.to) === 1) {
        edge.back = true
      } else if (!state.has(edge.to)) {
        state.set(edge.to, 1)
        stack.push({ id: edge.to, next: 0 })
      }
    }
  }

  // Longest path from a source over the edges that are left (now acyclic), in topological order.
  const layer = new Map<string, number>(order.map(id => [id, 0]))
  const waiting = new Map<string, number>(order.map(id => [id, 0]))

  for (const edge of edges) {
    if (!edge.back) {
      waiting.set(edge.to, (waiting.get(edge.to) ?? 0) + 1)
    }
  }

  const ready = order.filter(id => !waiting.get(id))

  for (let i = 0; i < ready.length; i++) {
    const id = ready[i]

    for (const edge of out.get(id) ?? []) {
      if (edge.back) {
        continue
      }

      layer.set(edge.to, Math.max(layer.get(edge.to) ?? 0, (layer.get(id) ?? 0) + 1))
      waiting.set(edge.to, (waiting.get(edge.to) ?? 1) - 1)
      !waiting.get(edge.to) && ready.push(edge.to)
    }
  }

  const rows: number[] = []

  const nodes = order.map(id => {
    const column = layer.get(id) ?? 0
    const row = rows[column] ?? 0

    rows[column] = row + 1

    return { id, layer: column, row }
  })

  return { edges, layers: rows.length, nodes }
}

// ─── csv ────────────────────────────────────────────────────────────────

export interface CsvTable {
  header: string[]
  rows: string[][]
}

/** Quoted fields, doubled quotes and ragged rows. Comma-delimited only, like the export. */
export function parseCsv(code: string): CsvTable {
  const text = code.replace(/\r\n?/g, '\n').replace(/^\n+/, '')
  const records: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false

  const endRow = () => {
    row.push(cell)
    cell = ''

    if (row.some(c => c.trim())) {
      records.push(row.map(c => c.trim()))
    }

    row = []
  }

  for (let i = 0; i < text.length; i++) {
    const ch = text[i]

    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"'
        i++
      } else if (ch === '"') {
        quoted = false
      } else {
        cell += ch
      }
    } else if (ch === '"' && !cell.trim()) {
      quoted = true
      cell = ''
    } else if (ch === ',') {
      row.push(cell)
      cell = ''
    } else if (ch === '\n') {
      endRow()
    } else {
      cell += ch
    }
  }

  endRow()

  const width = Math.max(0, ...records.map(r => r.length))
  const pad = (r: string[]) => Array.from({ length: width }, (_, i) => r[i] ?? '')
  const [header = [], ...rest] = records.map(pad)

  return { header, rows: rest }
}
