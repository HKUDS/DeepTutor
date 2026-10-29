'use client'

import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export interface Anchor {
  top: number
  left: number
  right: number
  bottom: number
}

export function anchorOf(element: Element | null | undefined): Anchor | null {
  if (!element) return null
  const rect = element.getBoundingClientRect()
  return { top: rect.top, left: rect.left, right: rect.right, bottom: rect.bottom }
}

/**
 * A card beside what it describes, the way calendar apps open an event:
 * to the right of the anchor when there is room, else to the left, and
 * kept inside the viewport. Outside presses and Escape dismiss it.
 */
export function AnchoredPopover({
  anchor,
  onClose,
  children,
  width = 340,
  label,
}: {
  anchor: Anchor
  onClose: () => void
  children: ReactNode
  width?: number
  label: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  useLayoutEffect(() => {
    closeRef.current = onClose
  }, [onClose])

  useLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    const gap = 8
    const margin = 12
    const height = node.offsetHeight
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const effectiveWidth = Math.min(width, viewportWidth - 2 * margin)
    let left = anchor.right + gap
    if (left + effectiveWidth > viewportWidth - margin) left = anchor.left - gap - effectiveWidth
    if (left < margin)
      left = Math.min(Math.max(margin, anchor.left), viewportWidth - effectiveWidth - margin)
    let top = anchor.top
    if (top + height > viewportHeight - margin) top = viewportHeight - margin - height
    node.style.top = `${Math.max(margin, top)}px`
    node.style.left = `${left}px`
    node.style.visibility = 'visible'
  }, [anchor, width, children])

  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      const target = event.target as Element | null
      if (ref.current?.contains(target as Node)) return
      // Menus and dialogs opened from inside the card live in their own portals.
      if (target?.closest?.('[role="dialog"], [role="menu"], [data-calendar-keep-popover]')) return
      closeRef.current()
    }
    const keys = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.stopPropagation()
        closeRef.current()
      }
    }
    // Next tick: the press that opened the card must not close it.
    const timer = setTimeout(() => document.addEventListener('pointerdown', dismiss), 0)
    document.addEventListener('keydown', keys)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', keys)
    }
  }, [])

  if (typeof document === 'undefined') return null
  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-label={label}
      data-calendar-popover
      className="dt-cal-popover"
      style={{
        width,
        top: anchor.top,
        left: anchor.right + 8,
        visibility: 'hidden',
      }}
    >
      {children}
    </div>,
    document.body
  )
}
