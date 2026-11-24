// The office canvas: Office 3D's OfficeCanvas (MIT, see ./LICENSE) as a typed Harvis
// component. A rAF loop draws only while the tab is visible and the canvas is on
// screen; zoom (Ctrl/Cmd + wheel, buttons) and drag-to-pan share the draw's projection,
// so a click lands on exactly what was drawn.
import { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

import {
  createOfficeLife,
  drawOfficeFrame,
  hitTestDesks,
  hitTestFigures,
  type OfficeEntry,
  type OfficeFrame,
  type OfficeView,
  officeLayout,
  zoomAbout
} from './render/office.js'

interface OfficeCanvasProps {
  entries: readonly OfficeEntry[]
  onPick?: (entry: null | OfficeEntry) => void
  selectedIndex: number
}

const FIT: OfficeView = { zoom: 1, panX: 0, panY: 0 }
const BTN =
  'rounded px-1.5 py-1 leading-none text-(--ui-text-secondary) hover:bg-[rgba(127,127,127,0.18)] active:bg-[rgba(127,127,127,0.28)]'

export function OfficeCanvas({ entries, onPick, selectedIndex }: OfficeCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const entriesRef = useRef(entries)
  const selectedRef = useRef(selectedIndex)
  const onPickRef = useRef(onPick)
  const frameRef = useRef<null | OfficeFrame>(null)
  const [view, updateView] = useState<OfficeView>(FIT)
  const viewRef = useRef(view)
  const dragRef = useRef<null | { id: number; moved: boolean; panX: number; panY: number; x: number; y: number }>(null)
  const suppressClickRef = useRef(false)
  const [dragging, setDragging] = useState(false)

  const setView = (next: OfficeView) => {
    // Native wheel events can arrive before React commits the next render.
    viewRef.current = next
    updateView(next)
  }

  entriesRef.current = entries
  selectedRef.current = selectedIndex
  onPickRef.current = onPick

  useEffect(() => {
    const container = containerRef.current
    const canvas = canvasRef.current
    const c2 = canvas?.getContext('2d')

    if (!container || !canvas || !c2) return
    const life = createOfficeLife()
    let raf = 0
    let onScreen = true
    const start = performance.now()

    const resize = () => {
      const rect = container.getBoundingClientRect()
      const dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1))
      const w = Math.max(200, Math.floor(rect.width))
      const h = Math.max(200, Math.floor(rect.height))
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
      canvas.width = Math.floor(w * dpr)
      canvas.height = Math.floor(h * dpr)
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(container)

    const tick = (now: number) => {
      raf = 0
      if (document.hidden || !onScreen) return
      try {
        frameRef.current = drawOfficeFrame(canvas, c2, entriesRef.current, life, (now - start) / 1000, selectedRef.current, viewRef.current)
      } catch (err) {
        // A draw error must never kill the loop.
        console.error('[office] draw error', err)
      }
      raf = requestAnimationFrame(tick)
    }
    const wake = () => {
      if (!raf && !document.hidden && onScreen) raf = requestAnimationFrame(tick)
    }
    const io =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(list => {
            onScreen = list[list.length - 1]?.isIntersecting ?? true
            wake()
          })
    io?.observe(container)
    document.addEventListener('visibilitychange', wake)
    wake()

    return () => {
      if (raf) cancelAnimationFrame(raf)
      ro.disconnect()
      io?.disconnect()
      document.removeEventListener('visibilitychange', wake)
    }
  }, [])

  const applyZoom = (nextZoom: number, ax?: number, ay?: number) => {
    const rect = containerRef.current?.getBoundingClientRect()
    const cssW = Math.max(200, rect ? Math.floor(rect.width) : 640)
    const cssH = Math.max(200, rect ? Math.floor(rect.height) : 400)
    setView(zoomAbout(cssW, cssH, officeLayout(entriesRef.current), viewRef.current, nextZoom, ax, ay))
  }
  const applyZoomRef = useRef(applyZoom)
  applyZoomRef.current = applyZoom

  useEffect(() => {
    const canvas = canvasRef.current

    if (!canvas) return
    const onWheel = (event: WheelEvent) => {
      // Plain wheel still scrolls the page; only modifier-wheel or pinch zooms.
      if (!event.ctrlKey && !event.metaKey) return
      event.preventDefault()
      const rect = canvas.getBoundingClientRect()
      const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY
      applyZoomRef.current(viewRef.current.zoom * Math.pow(1.0018, -delta), event.clientX - rect.left, event.clientY - rect.top)
    }
    canvas.addEventListener('wheel', onWheel, { passive: false })

    return () => canvas.removeEventListener('wheel', onWheel)
  }, [])

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (event.button !== 0) return
    const { panX, panY } = viewRef.current
    dragRef.current = { id: event.pointerId, moved: false, panX, panY, x: event.clientX, y: event.clientY }
  }

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current

    if (!d || d.id !== event.pointerId) return
    const dx = event.clientX - d.x
    const dy = event.clientY - d.y
    if (!d.moved) {
      if (Math.abs(dx) < 3 && Math.abs(dy) < 3) return
      d.moved = true
      setDragging(true)
      try {
        event.currentTarget.setPointerCapture(event.pointerId)
      } catch {
        // Capture is a nicety; the drag works without it.
      }
    }
    setView({ zoom: viewRef.current.zoom, panX: d.panX + dx, panY: d.panY + dy })
  }

  const endDrag = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current
    dragRef.current = null
    if (!d?.moved) return
    suppressClickRef.current = true
    setDragging(false)
    try {
      event.currentTarget.releasePointerCapture(d.id)
    } catch {
      // Already released.
    }
  }

  const onClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false
      return
    }
    const pick = onPickRef.current
    const frame = frameRef.current
    if (!pick || !frame) return
    const rect = event.currentTarget.getBoundingClientRect()
    const px = event.clientX - rect.left
    const py = event.clientY - rect.top
    const list = entriesRef.current
    // A figure in front of a desk wins, so a bot walking past can be clicked.
    const figure = hitTestFigures(frame, px, py)
    const index = figure >= 0 ? figure : hitTestDesks(list, frame, px, py)
    pick(index >= 0 ? (list[index] ?? null) : null)
  }

  const atFit = view.zoom === 1 && view.panX === 0 && view.panY === 0

  return (
    <div className="relative h-full min-h-[320px] w-full select-none" ref={containerRef}>
      <canvas
        aria-label="Bots office. Click a desk or a bot to open its chat."
        className={cn('block h-full w-full', onPick ? (dragging ? 'cursor-grabbing' : 'cursor-grab') : '')}
        onClick={onClick}
        onDoubleClick={() => setView(FIT)}
        onPointerCancel={endDrag}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        ref={canvasRef}
        style={{ touchAction: 'none' }}
        title="Click a desk or bot · Ctrl/⌘ + scroll to zoom · drag to pan · double-click to fit"
      />
      <div className="absolute right-2 top-2 flex items-center gap-0.5 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-0.5 py-0.5 text-xs shadow-sm">
        <button className={BTN} onClick={() => applyZoom(view.zoom / 1.3)} title="Zoom out" type="button">
          −
        </button>
        <button
          className={cn(BTN, 'min-w-[3.4rem] text-center font-medium tabular-nums')}
          onClick={() => setView(FIT)}
          title="Back to fit (100%)"
          type="button"
        >
          {Math.round(view.zoom * 100)}%
        </button>
        <button className={BTN} onClick={() => applyZoom(view.zoom * 1.3)} title="Zoom in" type="button">
          +
        </button>
      </div>
      {atFit && (
        <span className="pointer-events-none absolute bottom-2 left-2 text-[10px] text-(--ui-text-tertiary)">
          Ctrl/⌘ + scroll to zoom · drag to pan
        </span>
      )}
    </div>
  )
}
