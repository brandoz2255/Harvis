import { atom } from 'nanostores'

const STORAGE_KEY = 'harvis.composer.webSearch.v1'

const load = (): boolean => {
  try {
    return typeof window !== 'undefined' && window.localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

/** The composer's globe: search the web on every message until it is switched off. */
export const $webSearch = atom<boolean>(load())

export const setWebSearch = (on: boolean): void => {
  $webSearch.set(on)

  try {
    window.localStorage.setItem(STORAGE_KEY, on ? '1' : '0')
  } catch {
    // Private windows can refuse storage; the toggle still works for this page.
  }
}

export const toggleWebSearch = (): boolean => {
  const next = !$webSearch.get()

  setWebSearch(next)

  return next
}

let sentOn = false

/**
 * The prompt.submit field for the globe. It is left out until the globe has been on, so a user who never
 * touches it sends the same request as before; after that the off state is sent too, which is what switches a
 * session that was searching back to plain answers.
 */
export const webSearchParam = (): { web_search?: boolean } => {
  const on = $webSearch.get()

  sentOn = sentOn || on

  return sentOn ? { web_search: on } : {}
}
