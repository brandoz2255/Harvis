/**
 * localStorage that belongs to whoever was signed in, as opposed to the shell's own
 * look-and-feel. The origin is shared by everyone who uses this browser, so sign-out has
 * to take these with it or the next account sees the last one's drafts and transcripts.
 *
 * Keys are matched by prefix because connection-scoped stores append `.remote.<url>`.
 * Layout, theme and other per-installation preferences are not listed on purpose.
 */
/** Whose data the keys below hold; see {@link claimUserScopedStorage}. */
const OWNER_KEY = 'harvis.storageOwner'

const USER_KEYS = [
  'hermes:composer-drafts:v3',
  'hermes.desktop.composerQueue.v1',
  'hermes.desktop.lastSessionId',
  'hermes.desktop.lastRoute',
  'hermes.desktop.sessionOwnerHints.v1',
  'hermes.desktop.previewTabs.v2',
  'hermes.desktop.sessionPreviews.v1',
  'hermes.desktop.terminals.v1',
  'hermes.desktop.sessionTiles.v1',
  'hermes.desktop.sessionTiles.v2',
  'hermes.desktop.botChatSessions.v1',
  'hermes.desktop.sessionOrder',
  'hermes.desktop.pinnedSessions',
  'hermes.desktop.sessionColors',
  'hermes.desktop.sessionSeenCounts',
  'hermes.desktop.unreadFinishedSessions',
  'hermes.desktop.prBranchBySession',
  'hermes.desktop.prScannedSessions',
  'hermes.desktop.workspace-cwd',
  'hermes-bots-groups',
  'harvis.skill.drafted',
  'hermes.transcript-tail.v1',
  'hermes.transcript-tail.v2-index',
  'hermes.desktop.inflightTurnJournal.v1',
  OWNER_KEY
]

/** One entry per session or conversation; the key carries the session id. */
const USER_KEY_PREFIXES = [
  'hermes.transcript-tail.v2:',
  'hermes.desktop.inflightTurnJournal.v2:',
  'harvis-artifact-data:v1:'
]

const isUserKey = (key: string) =>
  USER_KEY_PREFIXES.some(prefix => key.startsWith(prefix)) ||
  USER_KEYS.some(base => key === base || key.startsWith(`${base}.`))

/** Removes the signed-in person's cached chats, drafts and session pointers. */
export function clearUserScopedStorage(): void {
  try {
    const store = window.localStorage
    const keys: string[] = []

    for (let i = 0; i < store.length; i += 1) {
      const key = store.key(i)

      if (key !== null && isUserKey(key)) {
        keys.push(key)
      }
    }

    keys.forEach(key => store.removeItem(key))
  } catch {
    // storage blocked: nothing was cached
  }
}

/**
 * Sign-out clears the previous account's cache, but a session that simply expired never
 * signs out: the next person to sign in on this browser would boot with its routes, drafts
 * and transcript tails. So the app records who the cache belongs to, and a different
 * signed-in user wipes it first.
 *
 * Returns 'switched' when it wiped another account's cache, which the app has already read
 * into memory, so the caller must restart it. Data of unknown ownership (written before
 * this existed) is adopted rather than dropped.
 */
export function claimUserScopedStorage(userId: string): 'same' | 'switched' {
  try {
    const store = window.localStorage
    const owner = store.getItem(OWNER_KEY)

    if (owner === userId) {
      return 'same'
    }

    if (owner === null) {
      store.setItem(OWNER_KEY, userId)

      return 'same'
    }

    clearUserScopedStorage()
    store.setItem(OWNER_KEY, userId)

    // Restarting only helps if the claim stuck; otherwise it would loop.
    return store.getItem(OWNER_KEY) === userId ? 'switched' : 'same'
  } catch {
    return 'same'
  }
}
