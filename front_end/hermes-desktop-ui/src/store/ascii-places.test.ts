import { describe, expect, it } from 'vitest'

import { parseAsciiPlaces } from './ascii-places'

describe('ascii places switch', () => {
  it('keeps known places and drops anything else', () => {
    expect(parseAsciiPlaces('chat, signin-full,bogus')).toEqual(['chat', 'signin-full'])
  })

  it('treats off as none, reset as the default, and no value as unset', () => {
    expect(parseAsciiPlaces('off')).toEqual([])
    expect(parseAsciiPlaces('')).toEqual([])
    expect(parseAsciiPlaces('reset')).toEqual(['chat', 'signin'])
    expect(parseAsciiPlaces(null)).toBeNull()
  })
})
