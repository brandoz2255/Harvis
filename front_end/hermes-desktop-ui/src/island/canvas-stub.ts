// jsdom has no canvas, image decoding or blob URLs. These stubs let the island run in a test:
// every 2D call is a no-op and every image "decodes" to a fixed size.
import { vi } from 'vitest'

const ctx: object = new Proxy(() => undefined, {
  apply: () => ctx,
  get: (_t, prop) => {
    if (prop === 'getImageData') {
      return (_x: number, _y: number, w: number, h: number) => ({ data: new Uint8ClampedArray(w * h * 4), height: h, width: w })
    }

    if (prop === 'measureText') {
      return () => ({ width: 8 })
    }

    return ctx
  },
  set: () => true
})

export interface CanvasStubs {
  blobUrls: Blob[]
  restore(): void
  revoked: string[]
}

export function installCanvasStubs(): CanvasStubs {
  const blobUrls: Blob[] = []
  const revoked: string[] = []

  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation((() => ctx) as never)

  class FakeImage {
    height = 96
    src = ''
    width = 128
    decode = () => Promise.resolve()
  }

  class FakeResizeObserver {
    disconnect() {}
    observe() {}
  }

  vi.stubGlobal('Image', FakeImage)
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
  URL.createObjectURL = (blob: Blob) => {
    blobUrls.push(blob)

    return `blob:fake/${blobUrls.length}`
  }
  URL.revokeObjectURL = (url: string) => void revoked.push(url)

  return {
    blobUrls,
    restore() {
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
    },
    revoked
  }
}
