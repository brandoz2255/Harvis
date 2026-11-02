// CSP for mod UI resources (open MCP Apps spec, rev 2026-01-26): built only from
// the domains the approved manifest declares, closed by default, never loosened.
import type { ModCsp } from './types'

// Same shape the server accepts (manifest.py ORIGIN_RE). The server has already
// validated the manifest; checking again here means a string that reaches the
// <meta> tag can never carry a quote, semicolon or space, whatever the source.
const ORIGIN_RE = /^(https:\/\/(\*\.)?[\w.-]+(:\d+)?|wss:\/\/[\w.-]+(:\d+)?)$/

const origins = (list: unknown): string[] =>
  Array.isArray(list) ? list.filter((d): d is string => typeof d === 'string' && ORIGIN_RE.test(d)) : []

const join = (list: string[]) => (list.length ? list.join(' ') : "'none'")

export function buildCsp(declared: ModCsp | null | undefined = {}): string {
  const d = declared ?? {}
  const resources = origins(d.resourceDomains)
  const extra = resources.length ? ` ${resources.join(' ')}` : ''
  const baseUri = origins(d.baseUriDomains)

  return [
    "default-src 'none'",
    `script-src 'self' 'unsafe-inline'${extra}`,
    `style-src 'self' 'unsafe-inline'${extra}`,
    `img-src 'self' data:${extra}`,
    `media-src 'self' data:${extra}`,
    `font-src 'self' data:${extra}`,
    `connect-src ${join(origins(d.connectDomains))}`,
    `base-uri ${baseUri.length ? baseUri.join(' ') : "'none'"}`,
    `frame-src ${join(origins(d.frameDomains))}`,
    "form-action 'none'"
  ].join('; ')
}

export const CSP_DEFAULT = buildCsp({})

/** Audit record (spec: a host SHOULD log CSP configs for security review). */
export function auditEntry(modName: string, hash: string, csp: string) {
  return { at: new Date().toISOString(), csp, hash, mod: modName }
}
