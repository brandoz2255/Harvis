/**
 * What `openExternalUrl` may do with a URL it was handed. The strings come from
 * the renderer, and from link clicks inside agent-written markdown, so the
 * OS-launch paths stay on a short list: web and mail links open in the system
 * handler, `file:` URLs are only ever revealed in the file manager (never run
 * through `shell.openPath`, which would launch a script or app bundle), and
 * everything else (`smb:`, `ms-msdt:`, custom schemes, ...) is refused.
 */
export type ExternalUrlTarget = { kind: 'external'; url: string } | { kind: 'file'; url: string }

const EXTERNAL_PROTOCOLS = new Set(['http:', 'https:', 'mailto:'])

export function classifyExternalUrl(rawUrl: unknown): ExternalUrlTarget | null {
  const raw = String(rawUrl ?? '').trim()

  if (!raw) {
    return null
  }

  let parsed: URL

  try {
    parsed = new URL(raw)
  } catch {
    return null
  }

  if (parsed.protocol === 'file:') {
    return { kind: 'file', url: parsed.toString() }
  }

  return EXTERNAL_PROTOCOLS.has(parsed.protocol) ? { kind: 'external', url: parsed.toString() } : null
}
