import type { PointerEvent as ReactPointerEvent } from 'react'

const DRAG_THRESHOLD = 4

/**
 * Press, drag, release. Listens on the window so a fast pointer that
 * leaves the element still drives the drag; a press that never travels
 * past a few pixels is a click. Escape abandons the drag.
 */
export function startGesture(
  event: ReactPointerEvent,
  {
    onStart,
    onMove,
    onClick,
    onDrop,
    onEnd,
  }: {
    onStart?: () => void
    onMove: (x: number, y: number) => void
    onClick?: () => void
    onDrop: () => void
    onEnd: () => void
  }
) {
  if (event.button !== 0) return
  event.preventDefault()
  const origin = { x: event.clientX, y: event.clientY }
  let moved = false
  const move = (pointer: PointerEvent) => {
    if (
      !moved &&
      Math.hypot(pointer.clientX - origin.x, pointer.clientY - origin.y) < DRAG_THRESHOLD
    )
      return
    if (!moved) {
      moved = true
      document.body.dataset.calendarDragging = 'true'
      onStart?.()
    }
    onMove(pointer.clientX, pointer.clientY)
  }
  const finish = (commit: boolean) => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    window.removeEventListener('pointercancel', cancel)
    window.removeEventListener('keydown', escape)
    delete document.body.dataset.calendarDragging
    if (commit) {
      if (moved) onDrop()
      else onClick?.()
    }
    onEnd()
  }
  const up = () => finish(true)
  const cancel = () => finish(false)
  const escape = (key: KeyboardEvent) => {
    if (key.key === 'Escape') finish(false)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
  window.addEventListener('pointercancel', cancel)
  window.addEventListener('keydown', escape)
}

/** The calendar day under a point, through whatever chips cover it. */
export function dayAtPoint(x: number, y: number): string | null {
  if (typeof document.elementsFromPoint !== 'function') return null
  for (const element of document.elementsFromPoint(x, y)) {
    const day = (element as HTMLElement).dataset?.calDay
    if (day) return day
  }
  return null
}
