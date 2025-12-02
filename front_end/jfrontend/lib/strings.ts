/**
 * Safe string utilities to prevent .trim() crashes on non-string values
 */

/**
 * Safely converts any value to a string, handling null/undefined
 */
export function toStr(value: any): string {
  if (value === null || value === undefined) {
    return ''
  }
  return String(value)
}

/**
 * Safely trims a string, handling non-string values
 */
export function safeTrim(value: any): string {
  return toStr(value).trim()
}

/**
 * Safely trims a string and returns empty string if result is empty
 */
export function safeTrimOrEmpty(value: any): string {
  const trimmed = safeTrim(value)
  return trimmed || ''
}

/**
 * Safely trims a string and returns null if result is empty
 */
export function safeTrimOrNull(value: any): string | null {
  const trimmed = safeTrim(value)
  return trimmed || null
}

/**
 * Safely trims a string and returns undefined if result is empty
 */
export function safeTrimOrUndefined(value: any): string | undefined {
  const trimmed = safeTrim(value)
  return trimmed || undefined
}

/**
 * Checks if a value is a non-empty string after trimming
 */
export function isNonEmptyString(value: any): boolean {
  return safeTrim(value).length > 0
}

/**
 * Safely extracts query parameter as string
 */
export function safeQueryParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) {
    return safeTrim(value[0])
  }
  return safeTrim(value)
}

/**
 * Safely extracts URL search params
 */
export function safeUrlParam(searchParams: URLSearchParams, key: string): string {
  return safeTrim(searchParams.get(key))
}

/**
 * Normalize a file path to be relative to workspace for backend APIs.
 * - Strips leading '/workspace/'
 * - Strips leading '/'
 */
export function toWorkspaceRelativePath(path: string): string {
  const p = safeTrim(path)
  if (!p) return ''
  if (p.startsWith('/workspace/')) return p.slice('/workspace/'.length)
  if (p.startsWith('/')) return p.slice(1)
  return p
}
