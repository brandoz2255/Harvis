/**
 * Citation markers in a saved answer. The server now rewrites every marker to
 * `[k]`, but older answers (and models that ignore the format) still carry
 * `【SOURCE 2】`, `[SOURCE 2]`, `[Source 2, Para 3]`, `[SOURCE 1, SOURCE 2]`, `[S2]`.
 * All of them become plain `[n]` so they line up with the numbered list below the answer.
 */

const MARKER = /\s*[[【]\s*(?:sources?|src|s(?=\d))\s*[:#]?\s*\d+[^\]】]*[\]】]/gi
const NUMBER = /\b(?:sources?|src|s)\s*[:#]?\s*(\d+)/gi

export function normalizeCitationMarkers(text: string): string {
  return text.replace(MARKER, marker => {
    const inner = marker.trim().slice(1, -1)
    const first = inner.match(/\d+/)?.[0]
    const numbers = [...inner.matchAll(NUMBER)].map(m => m[1])
    const picked = numbers.length > 0 ? numbers : first ? [first] : []

    return picked.length > 0 ? ' ' + [...new Set(picked)].map(n => `[${n}]`).join(' ') : marker
  })
}
