export interface LegalSection {
  heading: string
  body: string
}

export interface Legal {
  version: string
  terms: LegalSection[]
  acceptableUse: LegalSection[]
  houseRules: { required: boolean; version: string | null; points: string[] }
}

const sections = (raw: unknown): LegalSection[] =>
  Array.isArray(raw)
    ? raw.flatMap(s => {
        const { heading, body } = (s ?? {}) as Record<string, unknown>

        return typeof heading === 'string' && typeof body === 'string' ? [{ heading, body }] : []
      })
    : []

/**
 * The server's Terms of Use, Acceptable Use and house rules (public, no sign-in).
 * Resolves null when this server has no such page (an older Harvis answers 404 or
 * something that is not the expected JSON); rejects when it cannot be reached.
 */
export async function fetchLegal(): Promise<Legal | null> {
  const res = await fetch('/api/legal', { cache: 'no-store', credentials: 'include' })

  if (res.status >= 500) {
    throw new Error(`The server answered ${res.status}.`)
  }

  if (!res.ok) {
    return null
  }

  let body: Record<string, unknown>

  try {
    body = (await res.json()) as Record<string, unknown>
  } catch {
    return null
  }

  const terms = sections(body?.terms)
  const acceptableUse = sections(body?.acceptable_use)

  if (typeof body?.version !== 'string' || (!terms.length && !acceptableUse.length)) {
    return null
  }

  const rules = (body.house_rules ?? {}) as Record<string, unknown>
  const points = Array.isArray(rules.points) ? rules.points.filter((p): p is string => typeof p === 'string') : []

  return {
    version: body.version,
    terms,
    acceptableUse,
    houseRules: {
      required: rules.required === true && points.length > 0,
      version: typeof rules.version === 'string' ? rules.version : null,
      points
    }
  }
}
