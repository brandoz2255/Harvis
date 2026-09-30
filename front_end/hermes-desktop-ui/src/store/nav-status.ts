import { atom } from 'nanostores'

/**
 * Sidebar rows for features that are present but not installed yet, keyed by
 * route path. The value is the row's tooltip ("needs a 274 MB download"). A
 * dimmed row stays clickable: its page is where the install lives.
 */
export const $navDimmed = atom<Record<string, string>>({})

export function setNavDimmed(path: string, reason: null | string) {
  const { [path]: _previous, ...rest } = $navDimmed.get()

  $navDimmed.set(reason ? { ...rest, [path]: reason } : rest)
}
