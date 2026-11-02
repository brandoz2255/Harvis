// Tier 1 of a mod: plain theme values. A look names one of the app's own
// `--theme-*` custom properties (styles.css :root) and gives it a plain value.
//
// Mods are applied through one <style> element, not inline on <html>: the theme
// engine (themes/context.tsx applyTheme) writes the same properties inline on
// every skin change, so an inline mod value would be overwritten, and removing
// it would delete the theme's own value. A stylesheet rule marked !important
// beats those inline values, and switching the mod off simply empties the rule.
import type { LookValue, ModRow } from './types'

/** Every `--theme-*` token styles.css defines on :root, without the prefix. */
export const LOOK_TOKENS: readonly string[] = [
  'foreground',
  'primary',
  'secondary',
  'accent-soft',
  'midground',
  'warm',
  'background-seed',
  'sidebar-seed',
  'card-seed',
  'elevated-seed',
  'bubble-seed',
  'neutral-chrome',
  'neutral-sidebar',
  'neutral-card',
  'mix-chrome',
  'mix-sidebar',
  'mix-card',
  'mix-elevated',
  'mix-bubble',
  'fill-primary-accent-mix',
  'fill-secondary-accent-mix',
  'fill-tertiary-accent-mix',
  'fill-quaternary-accent-mix',
  'fill-quinary-accent-mix',
  'stroke-primary-accent-mix',
  'stroke-secondary-accent-mix',
  'stroke-tertiary-accent-mix',
  'stroke-quaternary-accent-mix',
  'row-hover-accent-mix',
  'row-active-accent-mix',
  'control-hover-accent-mix',
  'control-active-accent-mix'
]

const TOKEN_SET = new Set(LOOK_TOKENS)

// Mirrors manifest.py LOOK_KEY_RE / LOOK_BAD_RE / MAX_LOOK_LEN.
const LOOK_KEY_RE = /^[a-z][a-z0-9-]{0,47}$/
const LOOK_BAD_RE = /url\s*\(|image-set|@import|expression|[;{}<>\\]/i
const MAX_LOOK_LEN = 96

/** The server's plain-value rule: text, a number or true/false; text must not be able to fetch or break out. */
export function isPlainLookValue(value: unknown): value is LookValue {
  if (typeof value === 'boolean' || typeof value === 'number') {
    return Number.isFinite(value) || typeof value === 'boolean'
  }

  return typeof value === 'string' && value.length <= MAX_LOOK_LEN && !LOOK_BAD_RE.test(value)
}

/** The CSS custom property a look key controls, or null when it is not a real token. */
export function lookProperty(key: string): null | string {
  return LOOK_KEY_RE.test(key) && TOKEN_SET.has(key) ? `--theme-${key}` : null
}

/** A value ready to put after `--theme-x:`, or null when it must not be applied.
 *  Booleans have no token to drive. `!` is refused on top of the server rule so a
 *  value can never carry its own priority. */
export function lookCssValue(key: string, value: unknown): null | string {
  if (!isPlainLookValue(value) || typeof value === 'boolean') {
    return null
  }

  if (typeof value === 'number') {
    return key.includes('mix') ? `${value}%` : String(value)
  }

  const text = value.trim()

  return text && !text.includes('!') ? text : null
}

/** The looks that may be applied: key -> css value, for real tokens with plain values only. */
export function usableLooks(looks: Record<string, unknown> | null | undefined): Record<string, string> {
  const out: Record<string, string> = {}

  for (const [key, value] of Object.entries(looks ?? {})) {
    const prop = lookProperty(key)
    const css = prop ? lookCssValue(key, value) : null

    if (prop && css !== null) {
      out[prop] = css
    }
  }

  return out
}

/** Rows whose looks may paint: switched on AND approved at exactly this hash. */
export function rowsWithLooks(rows: readonly ModRow[]): ModRow[] {
  return rows.filter(
    row => row.status === 'on' && row.approved_hash === row.hash && Object.keys(row.manifest?.looks ?? {}).length > 0
  )
}

/** The stylesheet text for every on mod's looks (later mods in list order win a clash). */
export function buildLooksCss(rows: readonly ModRow[]): string {
  const merged: Record<string, string> = {}

  for (const row of rowsWithLooks(rows)) {
    Object.assign(merged, usableLooks(row.manifest.looks))
  }

  const decls = Object.entries(merged).map(([prop, value]) => `${prop}:${value} !important;`)

  return decls.length ? `:root:root{${decls.join('')}}` : ''
}

const STYLE_ID = 'harvis-mod-looks'

/** Paint these rows' looks, replacing whatever was painted before. No rows with looks removes the element. */
export function applyLooks(rows: readonly ModRow[], doc: Document = document): void {
  const css = buildLooksCss(rows)
  const existing = doc.getElementById(STYLE_ID)

  if (!css) {
    existing?.remove()

    return
  }

  const style = existing ?? doc.createElement('style')
  style.id = STYLE_ID
  style.textContent = css

  if (!existing) {
    doc.head.appendChild(style)
  }
}
