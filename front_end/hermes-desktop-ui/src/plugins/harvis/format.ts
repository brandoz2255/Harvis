export function relativeTime(iso: string): string {
  const then = Date.parse(iso)

  if (Number.isNaN(then)) {
    return ''
  }

  const seconds = Math.round((Date.now() - then) / 1000)

  if (seconds < 60) {
    return 'just now'
  }

  const minutes = Math.round(seconds / 60)

  if (minutes < 60) {
    return `${minutes}m ago`
  }

  const hours = Math.round(minutes / 60)

  if (hours < 24) {
    return `${hours}h ago`
  }

  const days = Math.round(hours / 24)

  return days < 30 ? `${days}d ago` : new Date(then).toLocaleDateString()
}

export function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000)

  if (s < 60) {
    return `${s}s`
  }

  const m = Math.floor(s / 60)

  return m < 60 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`
}

export function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k` : `${n}`
}
