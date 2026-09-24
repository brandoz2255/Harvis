import { atom } from '@hermes/plugin-sdk'

/** A finished run the user reopened from the mode pill; active runs dock on their own. */
export const $dockedRun = atom<null | string>(null)
