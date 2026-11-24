// Types for office.js, the Office 3D renderer the BOTS tab draws with.

export type OfficeState = 'busy' | 'idle' | 'offline' | 'unknown'

export interface OfficeEntry {
  /** Source-qualified roster identity (botRosterKey). */
  key: string
  /** Seeds the figure's gesture phase; the same as key. */
  profile: string
  display_name: string
  color: null | string
  state: OfficeState
  /** Unix seconds of the last real activity, only while idle. */
  idle_since: null | number
  /** A real session title, only while busy. Never invented. */
  task: null | string
}

export interface OfficeView {
  zoom: number
  panX: number
  panY: number
}

export interface OfficeLayout {
  cols: number
  rows: number
  worldW: number
  worldH: number
  workH: number
  loungeY0: number
  lounges: { x: number; y: number }[]
}

export interface OfficeFrame {
  ox: number
  oy: number
  scale: number
  zoom: number
  layout: OfficeLayout
  hits: { index: number; x: number; y: number; r: number }[]
}

export interface OfficeBubble {
  /** 'real' carries a real session title; 'sim' is decorative chatter and is drawn dashed. */
  kind: 'real' | 'sim'
  text: string
  until: number
}

export type OfficePlace =
  | { kind: 'desk'; index: number }
  | { kind: 'seat'; index: number; total: number }
  | { kind: 'spot'; x: number; index: number }
  | { kind: 'door' }

export interface OfficeFigure {
  index: number
  key: string
  x: number
  y: number
  mode: 'desk' | 'seat' | 'stand' | 'walk'
  seat: null | OfficePlace
  dir: [number, number]
  walkStart: number
  bubble: null | OfficeBubble
}

export interface OfficeLife {
  update(entries: readonly OfficeEntry[], layout: OfficeLayout, tSec: number): OfficeFigure[]
}

export const DOOR_X: number
export function route(from: OfficePlace, to: OfficePlace, layout: OfficeLayout): [number, number][]

export function createOfficeLife(): OfficeLife
export function officeLayout(entries: readonly OfficeEntry[]): OfficeLayout
export function drawOfficeFrame(
  canvas: HTMLCanvasElement,
  c: CanvasRenderingContext2D,
  entries: readonly OfficeEntry[],
  life: null | OfficeLife,
  tSec: number,
  selectedIndex: number,
  view: OfficeView
): OfficeFrame
export function hitTestFigures(frame: null | OfficeFrame, px: number, py: number): number
export function hitTestDesks(entries: readonly OfficeEntry[], frame: null | OfficeFrame, px: number, py: number): number
export function zoomAbout(cssW: number, cssH: number, layout: OfficeLayout, view: OfficeView, nextZoom: number, ax?: number, ay?: number): OfficeView
