export interface ArtLimits {
  readonly maxFiles: number
  readonly maxFileBytes: number
  readonly maxPathLength: number
  readonly maxTotalBytes: number
}

export interface ArtEntry {
  path: string
  size: number
  value: ArrayBuffer | Blob
}

export const LIMITS: ArtLimits
export const ANCHOR_FILE: string

export class ArtError extends Error {}

export function isArtPath(path: unknown): path is string
export function isArrayBuffer(value: unknown): value is ArrayBuffer
export function isBlob(value: unknown): value is Blob
export function readArtFiles(data: unknown): ArtEntry[]
