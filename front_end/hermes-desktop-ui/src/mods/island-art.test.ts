import { describe, expect, it, vi } from 'vitest'

import { LIMITS } from '@/island/engine/stardew/art-files.js'
import { fakePng } from '@/island/engine/test/fixtures.js'

import { ArtFolderError, type ArtStore, type ArtTarget, type ArtView, IslandArt, readArtFolder } from './island-art'
import type { IslandArtFiles, IslandArtStatus } from './island-bridge'

/** A picked File whose webkitRelativePath is set, the way a directory input reports it. */
function pickedFile(path: string, bytes: ArrayBuffer | number = 4): File {
  const data = typeof bytes === 'number' ? new Uint8Array(bytes) : new Uint8Array(bytes.slice(0))
  const file = new File([data], path.split('/').pop() ?? path)

  Object.defineProperty(file, 'webkitRelativePath', { value: path })

  return file
}


describe('readArtFolder', () => {
  it('strips the picked folder name so paths match the importer output', async () => {
    const files = await readArtFolder([
      pickedFile('stardew-assets/LooseSprites/Cursors.png', fakePng()),
      pickedFile('stardew-assets/Maps/Town.tbin', 8),
      pickedFile('stardew-assets/IMPORT_LOG.txt', 3)
    ])

    expect(Object.keys(files).sort()).toEqual(['LooseSprites/Cursors.png', 'Maps/Town.tbin'])
    expect(files['LooseSprites/Cursors.png']).toBeInstanceOf(ArrayBuffer)
  })

  it('finds the root from the cursor sheet even when the folder is nested deeper', async () => {
    const files = await readArtFolder([
      pickedFile('home/me/out/LooseSprites/Cursors.png', fakePng()),
      pickedFile('home/me/out/Maps/a.png', fakePng()),
      pickedFile('home/me/other/Maps/b.png', fakePng())
    ])

    expect(Object.keys(files).sort()).toEqual(['LooseSprites/Cursors.png', 'Maps/a.png'])
  })

  it('drops the folder name when there is no cursor sheet, leaving the island to report what is missing', async () => {
    const files = await readArtFolder([pickedFile('out/Maps/a.png', fakePng())])

    expect(Object.keys(files)).toEqual(['Maps/a.png'])
  })

  it('refuses a folder with no art files', async () => {
    await expect(readArtFolder([pickedFile('docs/readme.txt', 3)])).rejects.toBeInstanceOf(ArtFolderError)
    await expect(readArtFolder([])).rejects.toThrow(/No \.png or \.tbin files/)
  })

  it('refuses a path that would climb out of the folder', async () => {
    await expect(readArtFolder([pickedFile('out/../../etc/Cursors.png', fakePng())])).rejects.toBeInstanceOf(ArtFolderError)
  })

  it('refuses too many files before reading any of them', async () => {
    const many = Array.from({ length: LIMITS.maxFiles + 1 }, (_, i) => pickedFile(`out/Maps/${i}.png`, 1))
    const read = vi.spyOn(File.prototype, 'arrayBuffer')

    await expect(readArtFolder(many)).rejects.toThrow(/Too many files/)
    expect(read).not.toHaveBeenCalled()
    read.mockRestore()
  })

  it('refuses a single oversized file and an oversized total without reading them', async () => {
    const big = pickedFile('out/Maps/big.png', 1)

    Object.defineProperty(big, 'size', { value: LIMITS.maxFileBytes + 1 })
    await expect(readArtFolder([big])).rejects.toThrow(/too large/)

    const each = LIMITS.maxFileBytes
    const sizes = Array.from({ length: LIMITS.maxTotalBytes / each + 1 }, (_, i) => {
      const f = pickedFile(`out/Maps/${i}.png`, 1)

      Object.defineProperty(f, 'size', { value: each })

      return f
    })

    await expect(readArtFolder(sizes)).rejects.toThrow(/add up to more than/)
  })
})

const statusOf = (state: IslandArtStatus['state'], message = '', custom = state === 'custom'): IslandArtStatus => ({ custom, message, state })

function setup(stored: IslandArtFiles | null = null, answer: IslandArtStatus = statusOf('custom')) {
  const calls: string[] = []
  const views: ArtView[] = []
  const target: ArtTarget = {
    clearArt: () => {
      calls.push('clear')

      return statusOf('builtin')
    },
    useArt: vi.fn(async (files: IslandArtFiles) => {
      calls.push(`use:${Object.keys(files).join(',')}`)

      return answer
    })
  }
  const store: ArtStore = {
    clear: vi.fn(async () => void calls.push('store.clear')),
    load: vi.fn(async () => stored),
    save: vi.fn(async () => void calls.push('store.save'))
  }
  const art = new IslandArt(target, store, view => views.push(view))

  return { art, calls, store, target, views }
}

const folder = () => [pickedFile('out/LooseSprites/Cursors.png', fakePng())]

describe('IslandArt', () => {
  it('shows a pick on the island and saves it once the island answers custom', async () => {
    const { art, calls, views } = setup()

    await art.pick(folder())
    expect(calls).toEqual(['use:LooseSprites/Cursors.png', 'store.save'])
    expect(views).toEqual([
      { custom: false, message: '', state: 'loading' },
      { custom: true, message: '', state: 'custom' }
    ])
  })

  it('does not keep files the island rejected, and says why', async () => {
    const { art, calls, store, views } = setup(null, statusOf('error', 'Missing: Maps/Town.tbin', false))

    await art.pick(folder())
    expect(calls).toEqual(['use:LooseSprites/Cursors.png'])
    expect(store.save).not.toHaveBeenCalled()
    expect(views.at(-1)).toEqual({ custom: false, message: 'Missing: Maps/Town.tbin', state: 'error' })
  })

  it('keeps working art on screen when a later pick fails', async () => {
    const { art, target, views } = setup()

    await art.pick(folder())
    vi.mocked(target.useArt).mockResolvedValueOnce(statusOf('error', 'bad', true))
    await art.pick(folder())

    expect(views.at(-1)).toEqual({ custom: true, message: 'bad', state: 'error' })
  })

  it('reports an unreadable folder without bothering the island', async () => {
    const { art, calls, views } = setup()

    await art.pick([pickedFile('docs/readme.txt', 3)])

    expect(calls).toEqual([])
    expect(views.at(-1)?.state).toBe('error')
    expect(views.at(-1)?.message).toMatch(/No \.png or \.tbin files/)
  })

  it('restores art from an earlier visit without writing it back', async () => {
    const stored = { 'LooseSprites/Cursors.png': new ArrayBuffer(4) }
    const ok = setup(stored)

    await ok.art.restore()
    expect(ok.calls).toEqual(['use:LooseSprites/Cursors.png'])
    expect(ok.store.save).not.toHaveBeenCalled()
    expect(ok.views.at(-1)).toEqual({ custom: true, message: '', state: 'custom' })
  })

  it('forgets restored art that no longer loads', async () => {
    const stored = { 'LooseSprites/Cursors.png': new ArrayBuffer(4) }
    const bad = setup(stored, statusOf('error', 'gone', false))

    await bad.art.restore()
    expect(bad.calls).toEqual(['use:LooseSprites/Cursors.png', 'store.clear'])
    expect(bad.views.at(-1)).toEqual({
      custom: false,
      message: 'Your saved art used the previous map. Choose your imported game-art folder to draw Pelican Town.',
      state: 'builtin',
    })
  })

  it('restores nothing when no folder was ever picked, and says it is built-in', async () => {
    const { art, calls, views } = setup(null)

    await art.restore()

    expect(calls).toEqual([])
    expect(views).toEqual([{ custom: false, message: '', state: 'builtin' }])
  })

  it('"Use built-in art" clears the island and forgets the files', async () => {
    const { art, calls, views } = setup()

    await art.pick(folder())
    art.clear()

    expect(calls).toEqual(['use:LooseSprites/Cursors.png', 'store.save', 'clear', 'store.clear'])
    expect(views.at(-1)).toEqual({ custom: false, message: '', state: 'builtin' })
  })

  it('discards a late island answer when the pick was superseded by a clear', async () => {
    const stored = null
    const calls: string[] = []
    const views: ArtView[] = []
    let release!: (status: IslandArtStatus) => void
    const target: ArtTarget = {
      clearArt: () => statusOf('builtin'),
      useArt: () => new Promise(r => { release = r })
    }
    const store: ArtStore = {
      clear: vi.fn(async () => void calls.push('store.clear')),
      load: vi.fn(async () => stored),
      save: vi.fn(async () => void calls.push('store.save'))
    }
    const art = new IslandArt(target, store, view => views.push(view))

    const pick = art.pick(folder())
    await new Promise(r => setTimeout(r)) // let readArtFolder finish and reach useArt
    art.clear()
    release(statusOf('custom'))
    await pick

    expect(store.save).not.toHaveBeenCalled()
    expect(views.at(-1)).toEqual({ custom: false, message: '', state: 'builtin' })
    expect(calls).toEqual(['store.clear'])
  })

  it('answers an error view instead of throwing when the island itself throws', async () => {
    const { art, target, views } = setup()
    vi.mocked(target.useArt).mockRejectedValueOnce(new Error('boom'))

    await art.pick(folder())

    expect(views.at(-1)?.state).toBe('error')
    expect(views.at(-1)?.message).toMatch(/Couldn't load/)
  })
})
