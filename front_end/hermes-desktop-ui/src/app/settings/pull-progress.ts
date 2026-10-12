/**
 * Reading a model download. POST /api/cookbook/download answers with
 * Server-Sent Events: one `data: {json}\n\n` block per line Ollama's /api/pull
 * prints, so the shapes are Ollama's:
 *
 *   {"status":"pulling manifest"}
 *   {"status":"pulling 2bada8a74506","digest":"sha256:2bada8a74506…","total":4661211808,"completed":1048576}
 *   {"status":"verifying sha256 digest"}
 *   {"status":"writing manifest"}
 *   {"status":"success"}
 *
 * and the backend adds two of its own: `{"error":"…"}` when the pull cannot start
 * or the model server cannot be reached, and `{"status":"done","final":true}`
 * once the stream has ended cleanly.
 *
 * A model is several layers, each with its own digest, total and completed bytes,
 * and they arrive one after another. Overall progress is the sum of completed
 * over the sum of totals across every layer seen so far.
 *
 * Pure on purpose (no fetch, no timers): the parser takes text chunks cut
 * anywhere, the tracker takes events and a clock.
 */

export interface PullEvent {
  completed?: number
  digest?: string
  error?: string
  final?: boolean
  status?: string
  total?: number
}

export interface PullProgress {
  /** Bytes downloaded across every layer seen so far. */
  completed: number
  /** The stream ended cleanly (`done` or Ollama's `success`). */
  done: boolean
  error: null | string
  /** 0-100, or null until a layer has reported a total. */
  percent: null | number
  /** Smoothed bytes per second, or null until two samples have arrived. */
  speed: null | number
  /** The last status line Ollama sent, as-is. */
  status: string
  /** Bytes in every layer seen so far. */
  total: number
}

export const EMPTY_PULL: PullProgress = {
  completed: 0,
  done: false,
  error: null,
  percent: null,
  speed: null,
  status: '',
  total: 0
}

/**
 * Turns text chunks into events. A chunk can end anywhere (mid-block, mid-JSON,
 * between the two newlines of a block separator, between a CR and its LF), so the
 * unfinished tail is held back until the rest arrives. Blocks that are comments
 * (`: keep-alive`) or not JSON are skipped, never fatal.
 */
export function createSseParser() {
  let buffer = ''

  const parseBlock = (block: string): PullEvent | null => {
    const data = block
      .split('\n')
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).replace(/^ /, ''))
      .join('\n')

    if (!data.trim()) {
      return null
    }

    try {
      const value: unknown = JSON.parse(data)

      return value && typeof value === 'object' && !Array.isArray(value) ? (value as PullEvent) : null
    } catch {
      return null
    }
  }

  return {
    /** The stream closed: whatever is left is the last block, sent without its blank line. */
    flush(): PullEvent[] {
      const rest = buffer
      buffer = ''
      const event = parseBlock(rest.replace(/\r\n?/g, '\n'))

      return event ? [event] : []
    },
    push(chunk: string): PullEvent[] {
      // A CR at the very end may be the first half of CRLF: keep it for the next chunk.
      buffer += chunk
      const complete = buffer.endsWith('\r') ? buffer.slice(0, -1) : buffer
      const held = buffer.endsWith('\r') ? '\r' : ''
      const blocks = complete.replace(/\r\n?/g, '\n').split('\n\n')
      buffer = (blocks.pop() ?? '') + held

      return blocks.flatMap(block => {
        const event = parseBlock(block)

        return event ? [event] : []
      })
    }
  }
}

const SMOOTHING = 0.3

/**
 * Folds events into one progress value. `now` is injected so tests (and the
 * speed number) do not depend on the wall clock.
 */
export function createPullTracker(now: () => number = () => Date.now()) {
  const layers = new Map<string, { completed: number; total: number }>()
  let state: PullProgress = EMPTY_PULL
  let lastBytes = 0
  let lastAt: null | number = null
  let speed: null | number = null

  const sums = () => {
    let completed = 0
    let total = 0

    for (const layer of layers.values()) {
      completed += Math.min(layer.completed, layer.total || layer.completed)
      total += layer.total
    }

    return { completed, total }
  }

  const sampleSpeed = (completed: number) => {
    const at = now()

    if (lastAt !== null && at > lastAt && completed >= lastBytes) {
      const instant = ((completed - lastBytes) / (at - lastAt)) * 1000
      speed = speed === null ? instant : speed + SMOOTHING * (instant - speed)
    }

    lastAt = at
    lastBytes = completed
  }

  return {
    apply(event: PullEvent): PullProgress {
      if (typeof event.error === 'string' && event.error) {
        state = { ...state, error: event.error }

        return state
      }

      const status = typeof event.status === 'string' ? event.status : state.status

      if (typeof event.total === 'number' && event.total > 0) {
        const key = event.digest || status
        const previous = layers.get(key)

        layers.set(key, {
          completed: typeof event.completed === 'number' ? event.completed : (previous?.completed ?? 0),
          total: event.total
        })
      }

      const { completed, total } = sums()
      const finished = event.final === true || status === 'success' || status === 'done'

      if (typeof event.total === 'number' && event.total > 0) {
        sampleSpeed(completed)
      }

      state = {
        completed: finished && total > 0 ? total : completed,
        done: finished || state.done,
        error: state.error,
        percent: finished ? 100 : total > 0 ? Math.min(100, Math.floor((completed / total) * 100)) : state.percent,
        speed: finished ? null : speed,
        status,
        total
      }

      return state
    },
    get value() {
      return state
    }
  }
}

/** Decimal units, the way Ollama prints sizes: 4.8 GB, 312 MB. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return '0 MB'
  }

  if (bytes >= 1e9) {
    return `${(bytes / 1e9).toFixed(1)} GB`
  }

  if (bytes >= 1e6) {
    return `${Math.round(bytes / 1e6)} MB`
  }

  return `${Math.max(1, Math.round(bytes / 1e3))} KB`
}

/** "1.2 GB of 4.8 GB" */
export function formatMeter(completed: number, total: number): string {
  return `${formatBytes(completed)} of ${formatBytes(total)}`
}

/** "12.4 MB/s", or an empty string while there is no reading yet. */
export function formatSpeed(bytesPerSecond: null | number): string {
  return bytesPerSecond === null || bytesPerSecond <= 0 ? '' : `${(bytesPerSecond / 1e6).toFixed(1)} MB/s`
}
