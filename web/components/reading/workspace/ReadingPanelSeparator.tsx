'use client'

import { useEffect, useRef, useState, type PointerEvent } from 'react'

/** Pointer capture keeps drag cleanup local, including cancel, removal, and unmount. */
export function ReadingPanelSeparator({
  label,
  width,
  min,
  max,
  direction,
  onResize,
}: {
  label: string
  width: number
  min: number
  max: number
  direction: 1 | -1
  onResize: (width: number) => void
}) {
  const drag = useRef<{ id: number; x: number; width: number } | null>(null)
  const [resizing, setResizing] = useState(false)
  const resize = (next: number) => onResize(Math.round(Math.min(max, Math.max(min, next))))
  const finish = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.id !== event.pointerId) return
    drag.current = null
    setResizing(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  useEffect(() => {
    if (!resizing) return
    const { cursor, userSelect } = document.body.style
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    return () => {
      document.body.style.cursor = cursor
      document.body.style.userSelect = userSelect
    }
  }, [resizing])

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={min}
      aria-valuemax={Math.floor(max)}
      aria-valuenow={width}
      onPointerDown={event => {
        if (event.button !== 0) return
        event.preventDefault()
        event.currentTarget.focus()
        event.currentTarget.setPointerCapture(event.pointerId)
        drag.current = { id: event.pointerId, x: event.clientX, width }
        setResizing(true)
      }}
      onPointerMove={event => {
        const current = drag.current
        if (!current || current.id !== event.pointerId) return
        resize(current.width + direction * (event.clientX - current.x))
      }}
      onPointerUp={finish}
      onPointerCancel={finish}
      onLostPointerCapture={finish}
      onKeyDown={event => {
        const step = (event.shiftKey ? 40 : 10) * direction
        const next = { ArrowLeft: width - step, ArrowRight: width + step, Home: min, End: max }[
          event.key
        ]
        if (next === undefined) return
        event.preventDefault()
        resize(next)
      }}
      className="group/resize relative z-10 hidden cursor-col-resize touch-none focus-visible:outline-2 focus-visible:outline-[var(--primary)] xl:block"
    >
      <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-[var(--border)] transition-colors group-hover/resize:bg-[var(--primary)] group-active/resize:bg-[var(--primary)]" />
    </div>
  )
}
