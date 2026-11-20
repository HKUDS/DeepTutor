'use client'

import { type ReactNode, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { regionFromDrag, type NormalisedBox } from '@/lib/pdf-page-geometry'

/**
 * Marking an area of a PDF page (#2741).
 *
 * Text selection cannot reach what has no text layer: a scanned page, a
 * figure, a formula, handwriting. In area mode a pointer drag — mouse, touch
 * or pen — draws a rectangle instead, and the page reports it in
 * page-normalised coordinates, the frame the server crops in.
 *
 * The capturing surface exists only while the mode is on. Off, the layer is
 * pointer-transparent: scrolling (touch included), text selection and picture
 * hotspots behave exactly as before. On, `touch-action: none` keeps a finger
 * drawing instead of scrolling — the cost of the mode, and why it is a mode.
 *
 * Mounted on the whole-page surface (not the cropped strip), so its own
 * client rect is the page the box is normalised against.
 */
export function PdfRegionLayer({
  locator,
  selecting,
  marked,
  actions,
  onSelect,
}: {
  locator: number
  /** Area mode is on: a drag on this page draws a rectangle. */
  selecting: boolean
  /** The area already marked on this page, drawn until it is used or dropped. */
  marked: NormalisedBox | null
  /** What can be done with the marked area, shown next to it. */
  actions?: ReactNode
  onSelect: (locator: number, box: NormalisedBox) => void
}) {
  const { t } = useTranslation()
  const surfaceRef = useRef<HTMLDivElement | null>(null)
  const startRef = useRef<{ x: number; y: number; pointerId: number } | null>(null)
  const [draft, setDraft] = useState<NormalisedBox | null>(null)

  if (!selecting && !marked) return null

  const surfaceRect = () => surfaceRef.current?.getBoundingClientRect() ?? null
  const finish = (event: React.PointerEvent<HTMLDivElement>, commit: boolean) => {
    const start = startRef.current
    if (!start || start.pointerId !== event.pointerId) return
    startRef.current = null
    setDraft(null)
    const rect = surfaceRect()
    if (!commit || !rect) return
    const box = regionFromDrag(start, { x: event.clientX, y: event.clientY }, rect)
    if (box) onSelect(locator, box)
  }

  const shown = draft ?? marked
  // Actions sit under the box when there is room, otherwise inside its top.
  const actionsBelow = marked ? marked.y1 < 0.88 : true

  return (
    <div
      ref={surfaceRef}
      data-region-layer={selecting ? 'selecting' : 'marked'}
      className={`absolute inset-0 z-10 ${selecting ? 'cursor-crosshair' : 'pointer-events-none'}`}
      style={selecting ? { touchAction: 'none' } : undefined}
      aria-label={selecting ? t('Drag to mark an area') : undefined}
      onPointerDown={
        selecting
          ? event => {
              // Primary button only; touch and pen report button 0 as well.
              if (event.button !== 0) return
              event.preventDefault()
              event.stopPropagation()
              event.currentTarget.setPointerCapture?.(event.pointerId)
              startRef.current = { x: event.clientX, y: event.clientY, pointerId: event.pointerId }
              setDraft(null)
            }
          : undefined
      }
      onPointerMove={
        selecting
          ? event => {
              const start = startRef.current
              const rect = surfaceRect()
              if (!start || start.pointerId !== event.pointerId || !rect) return
              setDraft(regionFromDrag(start, { x: event.clientX, y: event.clientY }, rect))
            }
          : undefined
      }
      onPointerUp={selecting ? event => finish(event, true) : undefined}
      onPointerCancel={selecting ? event => finish(event, false) : undefined}
    >
      {shown && (
        <div
          data-region-box={draft ? 'draft' : 'marked'}
          className="pointer-events-none absolute rounded-[3px] border-2 border-dashed border-[var(--primary)] bg-[color-mix(in_srgb,var(--primary)_12%,transparent)]"
          style={{
            left: `${shown.x0 * 100}%`,
            top: `${shown.y0 * 100}%`,
            width: `${(shown.x1 - shown.x0) * 100}%`,
            height: `${(shown.y1 - shown.y0) * 100}%`,
          }}
        />
      )}
      {marked && !draft && actions && (
        <div
          className="pointer-events-auto absolute z-10 flex flex-wrap items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--background)] p-1 shadow-lg"
          // Pointer events on the actions must not start a new rectangle.
          onPointerDown={event => event.stopPropagation()}
          style={{
            // Anchored to the box's nearer side, so the bar stays on the page.
            ...(marked.x0 < 0.5
              ? { left: `${marked.x0 * 100}%` }
              : { right: `${(1 - marked.x1) * 100}%` }),
            ...(actionsBelow
              ? { top: `calc(${marked.y1 * 100}% + 6px)` }
              : { top: `calc(${marked.y0 * 100}% + 6px)` }),
          }}
        >
          {actions}
        </div>
      )}
    </div>
  )
}
