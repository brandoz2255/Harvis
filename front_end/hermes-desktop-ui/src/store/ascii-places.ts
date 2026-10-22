import { persistString, storedString } from '@/lib/storage'

const KEY = 'harvis.ascii-places.v1'

/**
 * Where the drifting ASCII field shows. A trial switch while we decide where it
 * belongs: add `?ascii=chat,signin` (any mix, or `off`, or `reset`) to the
 * address and it sticks for this browser until changed.
 *
 * - `chat`: behind the empty new chat, middle kept clear for the wordmark
 * - `chat-always`: behind every chat, transcript included
 * - `signin`: the brand panel on the sign-in screen
 * - `signin-full`: the whole sign-in screen, behind the form
 */
export const ASCII_PLACES = ['chat', 'chat-always', 'signin', 'signin-full'] as const

export type AsciiPlace = (typeof ASCII_PLACES)[number]

const DEFAULT: AsciiPlace[] = ['chat', 'signin']

export function parseAsciiPlaces(value: null | string): AsciiPlace[] | null {
  if (value === null) {
    return null
  }

  if (value === 'reset') {
    return DEFAULT
  }

  return value
    .split(',')
    .map(part => part.trim())
    .filter((part): part is AsciiPlace => (ASCII_PLACES as readonly string[]).includes(part))
}

function load(): Set<AsciiPlace> {
  const fromUrl = typeof window === 'undefined' ? null : new URLSearchParams(window.location.search).get('ascii')
  const picked = parseAsciiPlaces(fromUrl)

  if (picked) {
    persistString(KEY, picked.join(','))

    return new Set(picked)
  }

  return new Set(parseAsciiPlaces(storedString(KEY)) ?? DEFAULT)
}

/** Read once per page load; the switch takes effect on reload. */
export const asciiPlaces: ReadonlySet<AsciiPlace> = load()
