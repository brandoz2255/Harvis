/**
 * String utility functions used by VibeCode components
 */

/** Safely trim a string, returning empty string for non-string values */
export function safeTrim(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (value == null) return ''
  return String(value).trim()
}

/** Convert any value to string safely */
export function toStr(value: unknown): string {
  if (typeof value === 'string') return value
  if (value == null) return ''
  return String(value)
}

/**
 * Convert an absolute container path to a workspace-relative path.
 * e.g. "/workspace/src/main.py" -> "src/main.py"
 */
export function toWorkspaceRelativePath(path: string): string {
  if (!path) return path
  return path
    .replace(/^\/workspace\//, '')
    .replace(/^workspace\//, '')
}
