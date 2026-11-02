import { describe, expect, it } from 'vitest'
import { showBotsIsland } from './bots-island-visibility'

describe('Bots island placement', () => {
  it('shows only in the idle primary Bots workspace', () => {
    expect(showBotsIsland(true, true, false, false, true)).toBe(true)
    expect(showBotsIsland(true, false, false, false, true)).toBe(false)
    expect(showBotsIsland(false, true, false, false, true)).toBe(false)
    expect(showBotsIsland(true, true, true, false, true)).toBe(false)
    expect(showBotsIsland(true, true, false, true, true)).toBe(false)
  })

  it('gives way to an open session so its thread is visible', () => {
    expect(showBotsIsland(true, true, false, false, true, true)).toBe(false)
  })

  it('hides when the account turned "Show the island" off', () => {
    expect(showBotsIsland(true, true, false, false, false)).toBe(false)
  })
})
