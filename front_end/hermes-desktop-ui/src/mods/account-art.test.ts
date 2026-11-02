import { afterEach, expect, it, vi } from 'vitest'
import { accountArtStore, idbArtStore } from './island-art'

// Minimal asynchronous IndexedDB double, including transaction completion.
it('keeps art per account and never restores the legacy unscoped entry', async () => {
  const data = new Map<string, unknown>()
  const db = {
    close: () => undefined,
    transaction: () => {
      const tx = {
        oncomplete: () => undefined,
        objectStore: () => ({
          get: (key: string) => request(() => data.get(key)),
          put: (value: unknown, key: string) => request(() => { data.set(key, value); return key }),
          delete: (key: string) => request(() => { data.delete(key); return undefined })
        })
      }
      function request(fn: () => unknown) {
        const req = { result: undefined as unknown }
        queueMicrotask(() => { req.result = fn(); tx.oncomplete() })
        return req
      }
      return tx
    }
  }
  vi.stubGlobal('indexedDB', { open: () => {
    const req = { result: db, onsuccess: () => undefined }
    queueMicrotask(() => req.onsuccess())
    return req
  } })
  const alice = accountArtStore('alice')
  const bob = accountArtStore('bob')
  const art = { 'Maps/Town.tbin': new Uint8Array([1]).buffer }
  await idbArtStore.save(art)
  expect(await alice.load()).toBeNull()
  await alice.save(art)
  expect(await bob.load()).toBeNull()
  expect(await alice.load()).toEqual(art)
  await bob.clear()
  expect(await alice.load()).toEqual(art)
})

afterEach(() => vi.unstubAllGlobals())
