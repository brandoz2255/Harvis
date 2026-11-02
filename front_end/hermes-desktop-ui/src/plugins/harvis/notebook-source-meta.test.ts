import { describe, expect, it } from 'vitest'

import {
  ingestNotice,
  insightsPending,
  insightsState,
  needsReindex,
  suggestedQuestions,
  UPLOAD_ACCEPT
} from './notebook-source-meta'

describe('notebook source metadata', () => {
  it('accepts the office, ebook and scanned-PDF types in the picker', () => {
    for (const ext of ['.pdf', '.pptx', '.xlsx', '.xlsm', '.epub']) {
      expect(UPLOAD_ACCEPT.split(',')).toContain(ext)
    }
  })

  it('reports insights only for ready sources and ignores unknown values', () => {
    expect(insightsState({ metadata: { insights_status: 'pending' }, status: 'ready' })).toBe('pending')
    expect(insightsState({ metadata: { insights_status: 'error' }, status: 'ready' })).toBe('error')
    expect(insightsState({ metadata: { insights_status: 'done' }, status: 'ready' })).toBe('done')
    expect(insightsState({ metadata: { insights_status: 'pending' }, status: 'processing' })).toBe('none')
    expect(insightsState({ metadata: null, status: 'ready' })).toBe('none')
    expect(insightsState({ metadata: { insights_status: 'weird' as never }, status: 'ready' })).toBe('none')
  })

  it('keeps only non-empty string questions', () => {
    expect(suggestedQuestions({ metadata: { suggested_questions: ['Why?', '', '  '] } })).toEqual(['Why?'])
    expect(suggestedQuestions({ metadata: { suggested_questions: 'nope' as never } })).toEqual([])
    expect(suggestedQuestions({})).toEqual([])
  })

  it('reads notices and the re-index flag', () => {
    expect(ingestNotice({ metadata: { ingest_notice: '  2 pages skipped ' } })).toBe('2 pages skipped')
    expect(ingestNotice({ metadata: null })).toBe('')
    expect(needsReindex({ metadata: { needs_reembed: true } })).toBe(true)
    expect(needsReindex({ metadata: {} })).toBe(false)
  })

  it('knows when to keep polling for summaries', () => {
    expect(insightsPending([{ metadata: { insights_status: 'pending' }, status: 'ready' }])).toBe(true)
    expect(insightsPending([{ metadata: { insights_status: 'done' }, status: 'ready' }])).toBe(false)
  })
})
