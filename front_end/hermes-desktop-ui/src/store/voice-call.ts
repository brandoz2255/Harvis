import { atom } from 'nanostores'

import { persistBoolean, storedBoolean } from '@/lib/storage'

/**
 * The Harvis assistant call, started from the titlebar's Harvis button. It
 * lives at the app level (app/harvis-chatter/voice-call.tsx) so it keeps going
 * on every page, and it talks in its own conversation
 * (store/voice-assistant.ts), never the open chat. The composer's own voice
 * button is a separate thing: it talks to the chat and reads replies aloud.
 * Only an explicit end (the X, a stop word, a fatal mic error) sets it false.
 */
export const $voiceCallLive = atom(false)

export const setVoiceCallLive = (live: boolean) => $voiceCallLive.set(live)

/** The call's card shrunk to the bottom bubble (the user's minimize). */
export const $voiceCallCompact = atom(false)

export const setVoiceCallCompact = (compact: boolean) => $voiceCallCompact.set(compact)

const HARVIS_MIC_ON_STORAGE_KEY = 'hermes.desktop.harvisMicOn'

/**
 * Whether the bottom "Harvis" mic pill is shown. The titlebar's Harvis button
 * is an on/off toggle for it: on shows the pill on every page and it stays
 * until the button is pressed again; off (the default) hides it and ends any
 * call. Remembered across reloads.
 */
export const $harvisMicOn = atom(storedBoolean(HARVIS_MIC_ON_STORAGE_KEY, false))

$harvisMicOn.subscribe(on => persistBoolean(HARVIS_MIC_ON_STORAGE_KEY, on))

export function toggleHarvisMic() {
  const on = !$harvisMicOn.get()

  $harvisMicOn.set(on)

  if (!on) {
    $voiceCallLive.set(false)
  }
}
