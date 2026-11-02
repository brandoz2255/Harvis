import { beforeEach, describe, expect, it } from 'vitest'

import {
  contextPayload,
  getContextLevels,
  isDefaultSelection,
  levelOf,
  requestQuestion,
  selectedSourceIds,
  setContextLevel,
  takePendingQuestion
} from './notebook-selection'
import type { Source } from './notebook-shared'

const src = (id: string, status: Source['status'] = 'ready') => ({ id, status }) as unknown as Source
const sources = [src('a'), src('b'), src('c', 'processing')]

beforeEach(() => {
  window.localStorage.clear()

  for (const id of ['a', 'b']) {
    setContextLevel('nb', id, 'full')
  }
})

describe('context levels', () => {
  it('defaults every source to full and sends only ready sources', () => {
    expect(contextPayload('nb', sources)).toEqual({
      notes: [],
      sources: [
        { id: 'a', mode: 'full' },
        { id: 'b', mode: 'full' }
      ]
    })
    expect(isDefaultSelection('nb', sources)).toBe(true)
  })

  it('stores a choice per notebook and drops off sources from the id list', () => {
    setContextLevel('nb', 'a', 'off')
    setContextLevel('nb', 'b', 'insights')

    expect(levelOf(getContextLevels('nb'), 'a')).toBe('off')
    expect(contextPayload('nb', sources).sources).toEqual([
      { id: 'a', mode: 'off' },
      { id: 'b', mode: 'insights' }
    ])
    expect(selectedSourceIds('nb', sources)).toEqual(['b'])
    expect(isDefaultSelection('nb', sources)).toBe(false)
    expect(contextPayload('other', sources).sources.every(s => s.mode === 'full')).toBe(true)
  })

  it('returns to the default when full is chosen again', () => {
    setContextLevel('nb', 'a', 'off')
    setContextLevel('nb', 'a', 'full')

    expect(getContextLevels('nb')).toEqual({})
  })

  it('persists across a reload of the module state', () => {
    setContextLevel('nb', 'a', 'insights')

    expect(JSON.parse(window.localStorage.getItem('harvis.notebooks.context-levels') ?? '{}')).toEqual({
      nb: { a: 'insights' }
    })
  })
})

describe('pending question mailbox', () => {
  it('hands a question to its own notebook once', () => {
    requestQuestion('nb', 'Why is the sky blue?')

    expect(takePendingQuestion('other')).toBe('')
    expect(takePendingQuestion('nb')).toBe('Why is the sky blue?')
    expect(takePendingQuestion('nb')).toBe('')
  })
})
