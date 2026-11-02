export { ArtError, LIMITS } from './art-files.js'

export interface ArtPreset {
  homeDoors: { x: number; y: number }[]
  map: string
  places: Record<string, { x: number; y: number }>
  view: { h: number; w: number; x: number; y: number }
}

export interface AssetSource {
  buffer(path: string): ArrayBuffer | undefined
  dispose(): void
  has(path: string): boolean
  image(path: string): Promise<CanvasImageSource>
}

export interface ArtScene {
  mapData: unknown
  pack: unknown
  preset: ArtPreset
  source: AssetSource
}

export function requiredFiles(preset?: ArtPreset): string[]
export function materialize(entries: { path: string; value: ArrayBuffer | Blob }[]): Promise<Map<string, ArrayBuffer>>
export function missingFiles(files: Map<string, ArrayBuffer>, preset?: ArtPreset): string[]
export function describeMissing(missing: string[]): string
export function createAssetSource(
  files: Map<string, ArrayBuffer>,
  options?: { makeImage?: (buf: ArrayBuffer) => Promise<CanvasImageSource> }
): AssetSource
export function loadArtScene(
  data: unknown,
  preset?: ArtPreset,
  options?: { makeImage?: (buf: ArrayBuffer) => Promise<CanvasImageSource> }
): Promise<ArtScene>
