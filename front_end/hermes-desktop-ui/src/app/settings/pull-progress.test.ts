import { describe, expect, it } from 'vitest'

import {
  createPullTracker,
  createSseParser,
  formatBytes,
  formatMeter,
  formatSpeed,
  type PullEvent
} from './pull-progress'

const block = (event: object) => `data: ${JSON.stringify(event)}\n\n`

/** Feeds `text` to a fresh parser in chunks of `size` characters. */
function parseInChunks(text: string, size: number): PullEvent[] {
  const parser = createSseParser()
  const out: PullEvent[] = []

  for (let i = 0; i < text.length; i += size) {
    out.push(...parser.push(text.slice(i, i + size)))
  }

  out.push(...parser.flush())

  return out
}

describe('createSseParser', () => {
  const stream =
    block({ status: 'pulling manifest' }) +
    block({ status: 'pulling aaa', digest: 'sha256:aaa', total: 100, completed: 10 }) +
    block({ status: 'success' }) +
    block({ status: 'done', final: true })

  it('reads whole blocks', () => {
    expect(parseInChunks(stream, stream.length).map(e => e.status)).toEqual([
      'pulling manifest',
      'pulling aaa',
      'success',
      'done'
    ])
  })

  it('gives the same events however the stream is cut', () => {
    const whole = parseInChunks(stream, stream.length)

    for (const size of [1, 2, 3, 5, 7, 13, 29]) {
      expect(parseInChunks(stream, size)).toEqual(whole)
    }
  })

  it('holds a half-finished JSON object until the rest arrives', () => {
    const parser = createSseParser()

    expect(parser.push('data: {"status":"pulling aaa","tot')).toEqual([])
    expect(parser.push('al":100}\n')).toEqual([])
    expect(parser.push('\n')).toEqual([{ status: 'pulling aaa', total: 100 }])
  })

  it('handles the blank line being split across chunks', () => {
    const parser = createSseParser()

    expect(parser.push('data: {"status":"a"}\n')).toEqual([])
    expect(parser.push('\ndata: {"status":"b"}\n\n')).toEqual([{ status: 'a' }, { status: 'b' }])
  })

  it('handles CRLF line endings, including a CR/LF pair cut in two', () => {
    const parser = createSseParser()

    expect(parser.push('data: {"status":"a"}\r')).toEqual([])
    expect(parser.push('\n\r')).toEqual([])
    expect(parser.push('\ndata: {"status":"b"}\r\n\r\n')).toEqual([{ status: 'a' }, { status: 'b' }])
  })

  it('does not split a multi-byte character in the status text', () => {
    const text = block({ status: 'pulling 模型 ✓' })

    expect(parseInChunks(text, 1)).toEqual([{ status: 'pulling 模型 ✓' }])
  })

  it('emits the last block when the stream closes without its blank line', () => {
    const parser = createSseParser()

    expect(parser.push('data: {"status":"success"}')).toEqual([])
    expect(parser.flush()).toEqual([{ status: 'success' }])
    expect(parser.flush()).toEqual([])
  })

  it('skips comments, keep-alives and blocks that are not JSON', () => {
    const text = ': keep-alive\n\n' + 'data: not json\n\n' + 'data: [1,2]\n\n' + block({ status: 'ok' })

    expect(parseInChunks(text, 4)).toEqual([{ status: 'ok' }])
  })

  it('passes the backend error event through', () => {
    expect(parseInChunks(block({ error: 'ollama unreachable at http://x: boom' }), 6)).toEqual([
      { error: 'ollama unreachable at http://x: boom' }
    ])
  })
})

describe('createPullTracker', () => {
  const clock = (...times: number[]) => {
    let i = 0

    return () => times[Math.min(i++, times.length - 1)]
  }

  it('has no percent until a layer reports a total', () => {
    const t = createPullTracker()
    const p = t.apply({ status: 'pulling manifest' })

    expect(p.percent).toBeNull()
    expect(p.status).toBe('pulling manifest')
    expect(p.total).toBe(0)
  })

  it('reports percent and bytes for one layer', () => {
    const t = createPullTracker()
    const p = t.apply({ status: 'pulling aaa', digest: 'sha256:aaa', total: 4_800_000_000, completed: 1_200_000_000 })

    expect(p.percent).toBe(25)
    expect(p.completed).toBe(1_200_000_000)
    expect(p.total).toBe(4_800_000_000)
    expect(formatMeter(p.completed, p.total)).toBe('1.2 GB of 4.8 GB')
  })

  it('sums completed over total across every layer, not the latest layer alone', () => {
    const t = createPullTracker()

    t.apply({ status: 'pulling aaa', digest: 'a', total: 800, completed: 800 })
    t.apply({ status: 'pulling bbb', digest: 'b', total: 200, completed: 0 })
    const p = t.apply({ status: 'pulling bbb', digest: 'b', total: 200, completed: 100 })

    // (800 + 100) / (800 + 200) = 90%, where the last layer alone would say 50%.
    expect(p.percent).toBe(90)
    expect(p.completed).toBe(900)
    expect(p.total).toBe(1000)
  })

  it('updates a layer in place instead of counting it twice', () => {
    const t = createPullTracker()

    t.apply({ digest: 'a', status: 'pulling a', total: 1000, completed: 100 })
    t.apply({ digest: 'a', status: 'pulling a', total: 1000, completed: 600 })
    const p = t.apply({ digest: 'a', status: 'pulling a', total: 1000, completed: 1000 })

    expect(p.total).toBe(1000)
    expect(p.percent).toBe(100)
  })

  it('never goes past 100 or counts more than a layer holds', () => {
    const t = createPullTracker()
    const p = t.apply({ digest: 'a', status: 'pulling a', total: 100, completed: 140 })

    expect(p.percent).toBe(100)
    expect(p.completed).toBe(100)
  })

  it('keeps the progress and shows the new status line for events with no sizes', () => {
    const t = createPullTracker()

    t.apply({ digest: 'a', status: 'pulling a', total: 100, completed: 50 })
    const p = t.apply({ status: 'verifying sha256 digest' })

    expect(p.percent).toBe(50)
    expect(p.status).toBe('verifying sha256 digest')
  })

  it('finishes on success, and on the backend done event', () => {
    const a = createPullTracker()
    a.apply({ digest: 'a', status: 'pulling a', total: 100, completed: 99 })
    const done = a.apply({ status: 'success' })

    expect(done.done).toBe(true)
    expect(done.percent).toBe(100)
    expect(done.completed).toBe(100)

    const b = createPullTracker()
    expect(b.apply({ status: 'done', final: true }).done).toBe(true)
  })

  it('records an error event without losing the progress so far', () => {
    const t = createPullTracker()

    t.apply({ digest: 'a', status: 'pulling a', total: 100, completed: 30 })
    const p = t.apply({ error: 'ollama pull 500: nope' })

    expect(p.error).toBe('ollama pull 500: nope')
    expect(p.percent).toBe(30)
    expect(p.done).toBe(false)
  })

  it('smooths the speed instead of jumping with each sample', () => {
    const t = createPullTracker(clock(0, 1000, 2000, 3000))

    expect(t.apply({ digest: 'a', status: 's', total: 1e9, completed: 0 }).speed).toBeNull()

    // 10 MB in the first second: the first reading is taken as it is.
    expect(t.apply({ digest: 'a', status: 's', total: 1e9, completed: 10e6 }).speed).toBeCloseTo(10e6)

    // A burst of 30 MB in the next second moves the reading part of the way: 10 + 0.3 * (30 - 10).
    expect(t.apply({ digest: 'a', status: 's', total: 1e9, completed: 40e6 }).speed).toBeCloseTo(16e6)

    // A stall pulls it back down, but not to zero at once.
    const stalled = t.apply({ digest: 'a', status: 's', total: 1e9, completed: 40e6 }).speed

    expect(stalled).toBeGreaterThan(0)
    expect(stalled).toBeLessThan(16e6)
  })

  it('reports no speed once the pull is finished', () => {
    const t = createPullTracker(clock(0, 1000, 2000))

    t.apply({ digest: 'a', status: 's', total: 100, completed: 0 })
    t.apply({ digest: 'a', status: 's', total: 100, completed: 50 })

    expect(t.apply({ status: 'success' }).speed).toBeNull()
  })

  it('goes from raw chunks to final progress end to end', () => {
    const text =
      block({ status: 'pulling manifest' }) +
      block({ status: 'pulling aaa', digest: 'sha256:aaa', total: 3000, completed: 1500 }) +
      block({ status: 'pulling bbb', digest: 'sha256:bbb', total: 1000, completed: 0 }) +
      block({ status: 'pulling bbb', digest: 'sha256:bbb', total: 1000, completed: 500 })

    const t = createPullTracker()
    let last = t.value

    for (const event of parseInChunks(text, 7)) {
      last = t.apply(event)
    }

    // (1500 + 500) / (3000 + 1000)
    expect(last.percent).toBe(50)
    expect(last.status).toBe('pulling bbb')
  })
})

describe('formatters', () => {
  it('formats bytes in decimal units', () => {
    expect(formatBytes(4_800_000_000)).toBe('4.8 GB')
    expect(formatBytes(312_000_000)).toBe('312 MB')
    expect(formatBytes(2_500)).toBe('3 KB')
    expect(formatBytes(0)).toBe('0 MB')
  })

  it('formats speed, and nothing while there is no reading', () => {
    expect(formatSpeed(12_400_000)).toBe('12.4 MB/s')
    expect(formatSpeed(null)).toBe('')
    expect(formatSpeed(0)).toBe('')
  })
})
