import { describe, expect, it } from 'vitest'

import {
  asCitations,
  citationLookup,
  hidePartialMarker,
  linkCitations,
  locatePassage,
  normalizeCitationMarkers
} from './notebook-citations'

describe('normalizeCitationMarkers', () => {
  it.each([
    ['Cells divide【SOURCE 2】.', 'Cells divide [2].'],
    ['Cells divide [SOURCE 2].', 'Cells divide [2].'],
    ['Cells divide [Source 2].', 'Cells divide [2].'],
    ['Cells divide [SOURCE 2, Para 3].', 'Cells divide [2].'],
    ['Cells divide [SOURCE 2: Para 3].', 'Cells divide [2].'],
    ['Cells divide [S2].', 'Cells divide [2].'],
    ['Cells divide [SOURCE: 2].', 'Cells divide [2].'],
    ['Cells divide [SOURCE 1, SOURCE 3].', 'Cells divide [1] [3].'],
    ['Cells divide [2].', 'Cells divide [2].']
  ])('%s', (input, expected) => {
    expect(normalizeCitationMarkers(input)).toBe(expected)
  })

  it('leaves ordinary brackets and prose alone', () => {
    const text = 'See [the docs] and array[0], Source code is open. [Sources] section.'

    expect(normalizeCitationMarkers(text)).toBe(text)
  })
})

describe('asCitations', () => {
  it('keeps the offsets and page of a located citation and drops junk', () => {
    const out = asCitations([
      { end_char: 40, page: 3, quote: 'q', snippet: 's', source_id: 'a', source_title: 'A', start_char: 10 },
      null,
      'x',
      { source_id: 7, start_char: -1, page: 0 }
    ])

    expect(out).toHaveLength(2)
    expect(out[0]).toMatchObject({ end_char: 40, page: 3, snippet: 's', source_id: 'a', start_char: 10 })
    expect(out[1]).toMatchObject({ page: null, source_id: null, start_char: null })
    expect(asCitations(undefined)).toEqual([])
  })
})

describe('citationLookup', () => {
  it('uses the citation index when it has one and the position otherwise', () => {
    const lookup = citationLookup([{ source_id: 'a' }, { index: 5, source_id: 'b' }, { source_id: 'c' }])

    expect(lookup.get(1)?.source_id).toBe('a')
    expect(lookup.get(5)?.source_id).toBe('b')
    expect(lookup.get(3)?.source_id).toBe('c')
  })
})

describe('linkCitations', () => {
  const known = new Set([1, 2])

  it('links only markers that have a citation', () => {
    expect(linkCitations('A [1] and B [2] but C [9].', known)).toBe('A [[1]](#cite-1) and B [[2]](#cite-2) but C [9].')
  })

  it('leaves code, escaped brackets and ordinary links alone', () => {
    const text = 'Use `a[1]` or \\[1] or [1](https://x.test).\n\n```\nb[2]\n```'

    expect(linkCitations(text, known)).toBe(text)
  })

  it('does nothing without citations', () => {
    expect(linkCitations('A [1].', new Set())).toBe('A [1].')
  })
})

describe('hidePartialMarker', () => {
  it('drops a half-written marker at the end only', () => {
    expect(hidePartialMarker('It held a lake [SOURCE 1')).toBe('It held a lake')
    expect(hidePartialMarker('It held a lake [1] and more')).toBe('It held a lake [1] and more')
  })
})

describe('locatePassage', () => {
  const content = 'Intro line.\nJezero crater\nheld a lake long ago.\nTail text.'
  const start = content.indexOf('Jezero')
  const end = content.indexOf(' long ago') + ' long ago.'.length

  it('trusts stored offsets when the text there matches the snippet', () => {
    expect(locatePassage(content, { end_char: end, snippet: 'Jezero crater held a lake', start_char: start })).toEqual({
      end,
      start
    })
  })

  it('searches the snippet, ignoring line breaks, when offsets are missing', () => {
    const found = locatePassage(content, { quote: 'Jezero crater held a lake long ago…' })

    expect(found && content.slice(found.start, found.end)).toBe('Jezero crater\nheld a lake long ago')
  })

  it('searches the snippet when the offsets no longer match the text', () => {
    const found = locatePassage(content, { end_char: 8, snippet: 'Tail text', start_char: 0 })

    expect(found && content.slice(found.start, found.end)).toBe('Tail text')
  })

  it('falls back to the start of the cited page, then to nothing', () => {
    expect(locatePassage(content, { page: 2, snippet: 'not in the text at all' }, [0, 12])).toEqual({
      end: 12,
      start: 12
    })
    expect(locatePassage(content, { snippet: 'not in the text at all' })).toBeNull()
  })
})
