// A mod package as a person pastes or drops it: {manifest, resources}. Only the
// shape is checked here; the server validates the manifest and computes the hash.
import type { ModPackage } from './types'

export function parseModPackage(text: string): ModPackage {
  let raw: unknown

  try {
    raw = JSON.parse(text)
  } catch {
    throw new Error('That is not valid JSON.')
  }

  const pkg = raw as Partial<ModPackage> | null

  if (!pkg || typeof pkg !== 'object' || !pkg.manifest || typeof pkg.manifest !== 'object' || Array.isArray(pkg.manifest)) {
    throw new Error('A mod package has a "manifest" object and a "resources" object.')
  }

  const resources = pkg.resources ?? {}

  if (
    typeof resources !== 'object' ||
    Array.isArray(resources) ||
    !Object.values(resources).every(value => typeof value === 'string')
  ) {
    throw new Error('"resources" must map file names to text.')
  }

  return { manifest: pkg.manifest, resources }
}
