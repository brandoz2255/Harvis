// Host side of "bring your own game art" for the island.
//
// The user runs scripts/island/import-stardew.mjs on their own machine, then picks its output
// folder here. The files are their own game files: they stay in this browser (IndexedDB on the
// Harvis origin), are handed to the in-page island by direct call, and are never uploaded or served.
import { ANCHOR_FILE, isArtPath, LIMITS } from '@/island/engine/stardew/art-files.js'

import { type IslandArtFiles, type IslandArtStatus } from './island-bridge'

const MiB = 1024 * 1024

export class ArtFolderError extends Error {}

/** The slice of the mounted island the controller drives. useArt never throws: it answers a status. */
export interface ArtTarget {
  clearArt(): IslandArtStatus
  useArt(files: IslandArtFiles): Promise<IslandArtStatus>
}

/** Where the picked files persist. Methods never throw: storage can be blocked or full. */
export interface ArtStore {
  clear(): Promise<void>
  load(): Promise<IslandArtFiles | null>
  save(files: IslandArtFiles): Promise<void>
}

const DB_NAME = 'harvis-island'
const STORE = 'art'
const KEY = 'files'

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1)

    req.onupgradeneeded = () => req.result.createObjectStore(STORE)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function run<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb()

  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE, mode)
      const req = fn(tx.objectStore(STORE))

      tx.oncomplete = () => resolve(req.result)
      tx.onerror = tx.onabort = () => reject(tx.error)
    })
  } finally {
    db.close()
  }
}

export function accountArtStore(accountId: string): ArtStore {
  return makeArtStore(`user:${encodeURIComponent(accountId)}`)
}

function makeArtStore(key: string): ArtStore {
  return {
  async clear() {
    try {
      await run('readwrite', s => s.delete(key))
    } catch {
      // storage is unavailable; nothing was kept
    }
  },
  async load() {
    try {
      return ((await run('readonly', s => s.get(key))) as IslandArtFiles | undefined) ?? null
    } catch {
      return null
    }
  },
  async save(files) {
    try {
      await run('readwrite', s => s.put(files, key))
    } catch {
      // private window or full disk: the art still works until the page closes
    }
  }
  }
}

// Legacy unscoped art is never restored for an account.
export const idbArtStore = makeArtStore(KEY)

const pathOf = (file: File) => (file.webkitRelativePath || file.name).replace(/\\/g, '/')

/**
 * Keep the .png and .tbin files of a picked folder, keyed by their path inside the importer's output
 * (so "Maps/Town.tbin", whatever the folder was called). Applies the island's own size limits
 * before reading any file, so an oversized pick is refused without loading it.
 */
export async function readArtFolder(picked: ArrayLike<File>): Promise<IslandArtFiles> {
  const all = Array.from(picked, file => ({ file, path: pathOf(file) }))
  const anchor = all.find(f => f.path === ANCHOR_FILE || f.path.endsWith(`/${ANCHOR_FILE}`))
  const rootLength = anchor ? anchor.path.length - ANCHOR_FILE.length : 0
  // No anchor: the picked folder's own name is the usual prefix; the island reports what is missing.
  const firstSegment = all[0]?.path.split('/')[0]
  const dropFirst = !anchor && !!firstSegment && all.every(f => f.path.startsWith(`${firstSegment}/`))
  const prefix = anchor ? anchor.path.slice(0, rootLength) : dropFirst ? `${firstSegment}/` : ''

  const keep = all
    .filter(f => f.path.startsWith(prefix))
    .map(f => ({ file: f.file, path: f.path.slice(prefix.length) }))
    .filter(f => isArtPath(f.path))

  if (keep.length === 0) {
    throw new ArtFolderError('No .png or .tbin files in that folder. Pick the folder the importer wrote.')
  }

  if (keep.length > LIMITS.maxFiles) {
    throw new ArtFolderError(`Too many files (${keep.length}; the limit is ${LIMITS.maxFiles}).`)
  }

  let total = 0

  for (const { file, path } of keep) {
    if (file.size > LIMITS.maxFileBytes) {
      throw new ArtFolderError(`${path} is too large (over ${LIMITS.maxFileBytes / MiB} MB).`)
    }

    total += file.size

    if (total > LIMITS.maxTotalBytes) {
      throw new ArtFolderError(`The files add up to more than ${LIMITS.maxTotalBytes / MiB} MB.`)
    }
  }

  const files: IslandArtFiles = {}

  for (const { file, path } of keep) {
    files[path] = await file.arrayBuffer()
  }

  return files
}

export interface ArtView {
  /** True while the island is drawing with the user's art (an error can leave it so). */
  custom: boolean
  message: string
  state: IslandArtStatus['state']
}

/**
 * Ties the folder picker, the browser-only store and the mounted island together.
 * A pick is shown by the island first and only persisted once the island answers `custom`,
 * so a folder with missing files never replaces working art. `seq` discards a late answer
 * from a superseded pick, restore or clear (e.g. an account switch mid-load).
 */
export class IslandArt {
  private custom = false
  private seq = 0
  private disposed = false

  constructor(
    private readonly target: ArtTarget,
    private readonly store: ArtStore,
    private readonly onView: (view: ArtView) => void
  ) {}

  /** Bring back the folder picked in an earlier visit, if any. */
  async restore() {
    const startedAt = this.seq
    const files = await this.store.load()

    if (this.disposed) {
      return
    }

    // Nothing stored (or the save never landed): say so, or an Explore remount keeps
    // announcing the previous mount's custom art. A pick that raced the load wins.
    if (!files) {
      if (startedAt === this.seq) {
        this.custom = false
        this.onView({ custom: false, message: '', state: 'builtin' })
      }

      return
    }

    this.seq++ // invalidate any in-flight pick
    this.onView({ custom: this.custom, message: '', state: 'loading' })
    const status = await this.use(files)

    if (!status) {
      return
    }

    // Map presets can change between releases. A folder saved for an older map cannot draw Town;
    // forget it rather than pinning the new island to a stale error state.
    if (status.state === 'error') {
      void this.store.clear()
      this.custom = false
      this.onView({
        custom: false,
        message: 'Your saved art used the previous map. Choose your imported game-art folder to draw Pelican Town.',
        state: 'builtin',
      })
      return
    }

    this.apply(status)
  }

  async pick(picked: ArrayLike<File>) {
    let files: IslandArtFiles

    try {
      files = await readArtFolder(picked)
    } catch (e) {
      this.onView({ custom: this.custom, message: e instanceof Error ? e.message : "Couldn't read that folder.", state: 'error' })

      return
    }

    if (this.disposed) {
      return
    }

    this.seq++ // invalidate any in-flight restore
    this.onView({ custom: this.custom, message: '', state: 'loading' })
    const status = await this.use(files)

    if (!status) {
      return
    }

    // Files that cannot be used are not kept; working art from before stays on screen.
    if (status.state === 'custom') {
      void this.store.save(files)
    }

    this.apply(status)
  }

  /** "Use built-in art": back to the default renderer and forget the files. */
  clear() {
    this.seq++
    this.target.clearArt()
    void this.store.clear()
    this.custom = false
    this.onView({ custom: false, message: '', state: 'builtin' })
  }

  /** The host unmounted; late answers go nowhere. */
  dispose() {
    this.disposed = true
    this.seq++
  }

  /** Null when the answer lost the race against a newer pick, restore or clear. */
  private async use(files: IslandArtFiles): Promise<IslandArtStatus | null> {
    const seq = this.seq
    let status: IslandArtStatus

    try {
      status = await this.target.useArt(files)
    } catch {
      status = { custom: this.custom, message: "Couldn't load those game files.", state: 'error' }
    }

    return this.disposed || seq !== this.seq ? null : status
  }

  private apply(status: IslandArtStatus) {
    this.custom = status.custom
    this.onView({ custom: status.custom, message: status.message, state: status.state })
  }
}
