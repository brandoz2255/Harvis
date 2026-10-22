import { describe, expect, it } from 'vitest'

import { fieldDensity, glyphFor, rippleStrength } from './ascii-field'

describe('ascii field', () => {
  it('is deterministic for the same cell and time', () => {
    expect(fieldDensity(12, 7, 3.5)).toBe(fieldDensity(12, 7, 3.5))
  })

  it('stays in range and leaves open ground between patches', () => {
    let blank = 0
    let drawn = 0

    for (let row = 0; row < 60; row++) {
      for (let col = 0; col < 200; col++) {
        const d = fieldDensity(col, row, 1)
        expect(d).toBeGreaterThanOrEqual(0)
        expect(d).toBeLessThanOrEqual(1)
        glyphFor(d) ? drawn++ : blank++
      }
    }

    expect(blank).toBeGreaterThan(drawn)
    expect(drawn).toBeGreaterThan(0)
  })

  it('draws nothing at zero density and a dense glyph at full density', () => {
    expect(glyphFor(0)).toBeNull()
    expect(glyphFor(1)?.glyph).toBe('@')
  })
})

describe('ripple', () => {
  it('is a ring that moves outward and fades', () => {
    expect(rippleStrength(0, 0)).toBeGreaterThan(0.9)
    expect(rippleStrength(0, 400)).toBe(0)
    expect(rippleStrength(300, 400)).toBeGreaterThan(rippleStrength(300, 200))
    expect(rippleStrength(600, 800)).toBeLessThan(rippleStrength(300, 400))
  })

  it('is gone once its time is up or before the click', () => {
    expect(rippleStrength(1050, 1400)).toBe(0)
    expect(rippleStrength(0, -1)).toBe(0)
  })
})
