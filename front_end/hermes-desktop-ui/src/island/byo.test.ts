import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { installCanvasStubs, type CanvasStubs } from './canvas-stub'
import { ANCHOR_FILE, ArtError, isArtPath, LIMITS, readArtFiles } from './engine/stardew/art-files.js'
import { createAssetSource, describeMissing, loadArtScene, materialize, missingFiles } from './engine/stardew/byo.js'
import { fakePng, TINY_PRESET, tinyFiles } from './engine/test/fixtures.js'

const MiB = 1024 * 1024

/** Looks like a Blob of `size` bytes to the island's checks, without allocating them. */
const blobOfSize = (size: number) => ({ size, [Symbol.toStringTag]: 'Blob' })

describe('art file rules', () => {
  it('accepts relative .png and .tbin paths and nothing else', () => {
    for (const ok of ['Maps/Town.tbin', 'LooseSprites/Cursors.png', 'a.png', 'Maps/my sheet-2.png']) {
      expect(isArtPath(ok), ok).toBe(true)
    }

    for (const bad of [
      '../Maps/x.png',
      'Maps/../x.png',
      '/etc/x.png',
      'Maps/.hidden.png',
      'Maps\\x.png',
      'Maps/x.xnb',
      'Maps/x.PNG',
      'Maps/x.json',
      'Maps/x.png/',
      '',
      `${'a/'.repeat(LIMITS.maxPathLength)}x.png`
    ]) {
      expect(isArtPath(bad), bad).toBe(false)
    }

    expect(isArtPath(42)).toBe(false)
  })

  it('refuses a message that is not a map of path to file data', () => {
    for (const data of [null, {}, { files: null }, { files: [] }, { files: 'x' }, { files: {} }]) {
      expect(() => readArtFiles(data)).toThrow(ArtError)
    }

    expect(() => readArtFiles({ files: { 'Maps/x.png': 'not bytes' } })).toThrow(/not file data/)
    expect(() => readArtFiles({ files: { 'Maps/x.png': new ArrayBuffer(0) } })).toThrow(/empty/)
    expect(() => readArtFiles({ files: { '../x.png': new ArrayBuffer(8) } })).toThrow(/Unexpected file name/)
  })

  it('refuses oversized payloads before reading any of them', () => {
    expect(() => readArtFiles({ files: { 'Maps/big.png': blobOfSize(LIMITS.maxFileBytes + 1) } })).toThrow(/too large/)

    const files: Record<string, unknown> = {}

    for (let i = 0; i <= LIMITS.maxTotalBytes / LIMITS.maxFileBytes; i++) {
      files[`Maps/p${i}.png`] = blobOfSize(LIMITS.maxFileBytes)
    }

    expect(() => readArtFiles({ files })).toThrow(/add up to more than/)

    const many: Record<string, ArrayBuffer> = {}

    for (let i = 0; i <= LIMITS.maxFiles; i++) {
      many[`Maps/m${i}.png`] = new ArrayBuffer(8)
    }

    expect(() => readArtFiles({ files: many })).toThrow(/Too many files/)
  })

  it('accepts both ArrayBuffer and Blob file data', () => {
    const entries = readArtFiles({ files: { 'Maps/a.png': new ArrayBuffer(8), 'Maps/b.png': new Blob([new Uint8Array(4)]) } })

    expect(entries.map(e => [e.path, e.size])).toEqual([
      ['Maps/a.png', 8],
      ['Maps/b.png', 4]
    ])
  })

  it('anchors on a file every import contains', () => {
    expect(ANCHOR_FILE).toBe('LooseSprites/Cursors.png')
    expect(Object.keys(tinyFiles())).toContain(ANCHOR_FILE)
  })
})

describe('materialize and missing files', () => {
  it('rejects bytes that do not start like a PNG or a map', async () => {
    await expect(materialize(readArtFiles({ files: { 'Maps/x.png': new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9]).buffer } }))).rejects.toThrow(
      /not a PNG image/
    )
    await expect(materialize(readArtFiles({ files: { 'Maps/x.tbin': fakePng() } }))).rejects.toThrow(/not a map file/)
  })

  it('lists required files and the map tilesheets that are absent', async () => {
    const files = tinyFiles()

    delete files['Maps/MenuTiles.png']
    delete files['Maps/tiny_sheet.png']

    const got = await materialize(readArtFiles({ files }))

    expect(missingFiles(got, TINY_PRESET)).toEqual(['Maps/MenuTiles.png', 'Maps/tiny_sheet.png'])
    expect(missingFiles(await materialize(readArtFiles({ files: tinyFiles() })), TINY_PRESET)).toEqual([])
  })

  it('says what is missing in one short line', () => {
    expect(describeMissing(['a.png'])).toBe('Missing from the folder you picked: a.png. Run the importer again.')
    expect(describeMissing(['a.png', 'b.png', 'c.png', 'd.png', 'e.png'])).toContain('a.png, b.png, c.png (+2 more)')
  })

  it('treats a map file that will not parse as an unusable import', async () => {
    const files = tinyFiles()

    files['Maps/Tiny.tbin'] = new TextEncoder().encode('tBIN10 then nothing useful').buffer as ArrayBuffer

    await expect(loadArtScene({ files }, TINY_PRESET)).rejects.toThrow(/Tiny.tbin could not be read/)
  })
})

describe('loadArtScene', () => {
  let stubs: CanvasStubs

  beforeEach(() => {
    stubs = installCanvasStubs()
  })

  afterEach(() => stubs.restore())

  it('builds a scene from posted files, decoding images from blob URLs made in this frame', async () => {
    const scene = await loadArtScene({ files: tinyFiles() }, TINY_PRESET)

    expect(scene.source.has('Maps/Tiny.tbin')).toBe(true)
    expect(stubs.blobUrls.length).toBeGreaterThanOrEqual(5) // 4 HUD sheets + the map's tilesheet
    expect(stubs.blobUrls.every(b => b.type === 'image/png')).toBe(true)
    expect(stubs.revoked.length).toBe(stubs.blobUrls.length) // each URL is released once decoded
  })

  it('stays on the default renderer when a required file is missing: nothing is decoded', async () => {
    const files = tinyFiles()

    delete files['LooseSprites/font_bold.png']

    await expect(loadArtScene({ files }, TINY_PRESET)).rejects.toThrow(/Missing from the folder you picked: LooseSprites\/font_bold.png/)
    expect(stubs.blobUrls).toEqual([])
  })

  it('reports an image that cannot decode as unusable files, not a crash', async () => {
    await expect(
      loadArtScene({ files: tinyFiles() }, TINY_PRESET, { makeImage: () => Promise.reject(new Error('corrupt')) })
    ).rejects.toThrow(/could not be read as game art/)
  })

  it('serves nothing after dispose', async () => {
    const source = createAssetSource(await materialize(readArtFiles({ files: tinyFiles() })))

    await expect(source.image('Maps/MenuTiles.png')).resolves.toBeDefined()
    source.dispose()
    await expect(source.image('Maps/MenuTiles.png')).rejects.toThrow()
    expect(source.buffer('Maps/Tiny.tbin')).toBeUndefined()
  })

  it('only decodes .png entries', async () => {
    const source = createAssetSource(await materialize(readArtFiles({ files: tinyFiles() })))

    await expect(source.image('Maps/Tiny.tbin')).rejects.toThrow()
    expect(LIMITS.maxFileBytes).toBe(8 * MiB)
  })
})
