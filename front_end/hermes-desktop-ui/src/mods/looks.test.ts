import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import { applyLooks, buildLooksCss, isPlainLookValue, LOOK_TOKENS, lookCssValue, lookProperty, usableLooks } from './looks'
import type { LookValue, ModRow } from './types'

const HASH = 'f'.repeat(64)

const row = (looks: Record<string, LookValue>, patch: Partial<ModRow> = {}): ModRow =>
  ({
    approved_at: null,
    approved_hash: HASH,
    created_at: '',
    hash: HASH,
    id: 1,
    manifest: { harvis_mod_version: '1', looks, name: 'tint', version: '1.0.0' },
    name: 'tint',
    source: 'user',
    status: 'on',
    status_reason: null,
    tiers: ['looks'],
    version: '1.0.0',
    ...patch
  }) as ModRow

afterEach(() => {
  document.getElementById('harvis-mod-looks')?.remove()
})

describe('look tokens', () => {
  it('every token the mods may set is a real --theme-* property in styles.css', () => {
    const css = readFileSync(join(__dirname, '..', 'styles.css'), 'utf8')

    for (const token of LOOK_TOKENS) {
      expect(css, `--theme-${token}`).toContain(`--theme-${token}:`)
    }
  })

  it('maps only real tokens', () => {
    expect(lookProperty('primary')).toBe('--theme-primary')
    expect(lookProperty('background')).toBeNull() // only the -seed tokens exist
    expect(lookProperty('not-a-token')).toBeNull()
    expect(lookProperty('Primary')).toBeNull()
    expect(lookProperty('primary; color')).toBeNull()
  })
})

describe('plain values (the server rule)', () => {
  it.each(['#112233', 'rgb(1, 2, 3)', 'oklch(0.2 0.1 200)', 'Inter, sans-serif'])('accepts %s', value => {
    expect(isPlainLookValue(value)).toBe(true)
  })

  it.each([
    'url(https://evil.example/x.png)',
    'URL (x)',
    'image-set(x 1x)',
    '@import "x"',
    'expression(alert(1))',
    'red; background: blue',
    'red}body{x:y',
    '<b>',
    'back\\slash',
    'x'.repeat(97)
  ])('refuses %s', value => {
    expect(isPlainLookValue(value)).toBe(false)
  })

  it('accepts numbers and booleans as values, refuses non-finite numbers', () => {
    expect(isPlainLookValue(0.5)).toBe(true)
    expect(isPlainLookValue(true)).toBe(true)
    expect(isPlainLookValue(Number.POSITIVE_INFINITY)).toBe(false)
    expect(isPlainLookValue({})).toBe(false)
    expect(isPlainLookValue(null)).toBe(false)
  })

  it('never lets a value carry its own priority', () => {
    expect(lookCssValue('primary', 'red !important')).toBeNull()
    expect(lookCssValue('primary', '  ')).toBeNull()
    expect(lookCssValue('primary', true)).toBeNull()
  })

  it('writes percent for mix numbers', () => {
    expect(lookCssValue('mix-card', 30)).toBe('30%')
    expect(lookCssValue('radius', 4)).toBe('4')
  })
})

describe('usableLooks', () => {
  it('keeps real tokens with plain values and drops the rest', () => {
    expect(
      usableLooks({
        primary: '#101010',
        'not-a-token': 'red',
        foreground: 'url(x)',
        'x; y': 'red'
      })
    ).toEqual({ '--theme-primary': '#101010' })
  })
})

describe('buildLooksCss / applyLooks', () => {
  it('paints only mods that are on AND approved at their current hash', () => {
    expect(buildLooksCss([row({ primary: '#111111' })])).toBe(':root:root{--theme-primary:#111111 !important;}')
    expect(buildLooksCss([row({ primary: '#111111' }, { status: 'off' })])).toBe('')
    expect(buildLooksCss([row({ primary: '#111111' }, { status: 'draft' })])).toBe('')
    expect(buildLooksCss([row({ primary: '#111111' }, { status: 'broken' })])).toBe('')
    expect(buildLooksCss([row({ primary: '#111111' }, { approved_hash: null })])).toBe('')
    expect(buildLooksCss([row({ primary: '#111111' }, { approved_hash: 'e'.repeat(64) })])).toBe('')
  })

  it('adds a stylesheet when a mod turns on and removes it when it turns off', () => {
    applyLooks([row({ primary: '#111111' })])

    const style = document.getElementById('harvis-mod-looks')
    expect(style?.textContent).toContain('--theme-primary:#111111 !important')

    applyLooks([row({ primary: '#111111' }, { status: 'off' })])
    expect(document.getElementById('harvis-mod-looks')).toBeNull()
  })

  it('replaces rather than stacks on repeat applies, and never touches inline theme values', () => {
    document.documentElement.style.setProperty('--theme-primary', '#abcdef')
    applyLooks([row({ primary: '#111111' })])
    applyLooks([row({ primary: '#222222' })])

    expect(document.querySelectorAll('#harvis-mod-looks')).toHaveLength(1)
    expect(document.getElementById('harvis-mod-looks')?.textContent).toContain('#222222')
    expect(document.documentElement.style.getPropertyValue('--theme-primary')).toBe('#abcdef')

    document.documentElement.style.removeProperty('--theme-primary')
  })
})
