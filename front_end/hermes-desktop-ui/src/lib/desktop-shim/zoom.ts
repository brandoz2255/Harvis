// Browser stand-in for the desktop app's window zoom (Appearance ▸ UI scale).
//
// Electron zooms the whole webContents. A page cannot do that, so this scales
// the root font size instead: nearly every size in the UI is in rem, so text,
// spacing and panel widths grow together, while pointer coordinates stay 1:1
// (factor() is 1, so nothing that maps mouse positions needs to compensate).

import { localStore } from './api'

// Harvis runs on laptops and big monitors, not a dense desktop window: the
// web build starts one step above actual size.
const DEFAULT_PERCENT = 110
const MIN_PERCENT = 75
const MAX_PERCENT = 200

const stored = localStore('hermes.web.zoomPercent')
const listeners = new Set<(payload: { level: number; percent: number }) => void>()

const clamp = (percent: number) => Math.min(MAX_PERCENT, Math.max(MIN_PERCENT, Math.round(percent)))

// Chromium's zoom level is log base 1.2 of the factor; kept so the payload
// matches what the Electron bridge sends.
const levelFor = (percent: number) => Math.log(percent / 100) / Math.log(1.2)

let current = clamp(stored.read<number>(DEFAULT_PERCENT))

function apply(percent: number): void {
  document.documentElement.style.fontSize = `calc(var(--dt-base-size, 1rem) * ${percent / 100})`
}

export const zoom = {
  get: async () => ({ level: levelFor(current), percent: current }),
  factor: () => 1,
  setPercent(percent: number) {
    current = clamp(percent)
    stored.write(current)
    apply(current)
    const payload = { level: levelFor(current), percent: current }
    listeners.forEach(listener => listener(payload))
  },
  onChanged(callback: (payload: { level: number; percent: number }) => void) {
    listeners.add(callback)
    return () => {
      listeners.delete(callback)
    }
  }
}

// The browser's own Ctrl/Cmd +/- still zooms the page on top of this.
export function installZoom(): void {
  apply(current)
}
