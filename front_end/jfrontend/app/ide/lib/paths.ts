"use client"

/**
 * Convert absolute path to relative path
 * Strips leading / and condenses multiple slashes
 */
export function toRel(path: string): string {
  if (!path) return ''
  return path.replace(/^\/+/, '').replace(/\/+/g, '/')
}

/**
 * Join directory and filename as relative path
 * Handles empty dir (root) and ensures proper formatting
 */
export function joinRel(dir: string, name: string): string {
  const cleanDir = toRel(dir)
  const cleanName = toRel(name)
  
  if (!cleanDir) return cleanName
  if (!cleanName) return cleanDir
  
  return `${cleanDir}/${cleanName}`.replace(/\/+/g, '/')
}

/**
 * Convert relative path to absolute workspace path
 * Used for display and file operations
 */
export function toAbs(path: string): string {
  if (!path) return '/workspace'
  return `/workspace/${toRel(path)}`.replace(/\/+/g, '/')
}

/**
 * Get parent directory of a relative path
 */
export function getParent(path: string): string {
  const rel = toRel(path)
  if (!rel) return ''
  const parts = rel.split('/')
  parts.pop()
  return parts.join('/')
}

/**
 * Get filename from a relative path
 */
export function getFilename(path: string): string {
  const rel = toRel(path)
  if (!rel) return ''
  return rel.split('/').pop() || ''
}
