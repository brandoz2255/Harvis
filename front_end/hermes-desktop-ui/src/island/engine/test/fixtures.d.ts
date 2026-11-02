import type { ArtPreset } from '../stardew/byo.js'

export function buildTbin(spec: {
  layers: { h: number; id: string; tiles: number[]; w: number }[]
  sheets: { id: string; image: string; props?: Record<string, string> }[]
}): ArrayBuffer
export function tinyMap(w?: number, h?: number): ArrayBuffer
export function fakePng(extra?: number): ArrayBuffer
export function tinyFiles(map?: string, w?: number, h?: number): Record<string, ArrayBuffer>
export const TINY_PRESET: ArtPreset
