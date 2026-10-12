import { describe, expect, it } from 'vitest'

import { normalizeCitationMarkers } from './notebook-citations'

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
