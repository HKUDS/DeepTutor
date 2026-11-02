'use client'

import Link from 'next/link'
import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import PartnerAvatar from '@/components/partners/PartnerAvatar'
import type { PartnerNavigationData } from '@/hooks/usePartnerNavigation'
import { rosterFade, rosterLens } from './roster-lens'

type RosterPartner = PartnerNavigationData['partners'][number]

/** How far compression reaches in from each edge; just over one item. */
const ZONE = 52
/** Past this depth a click brings the partner forward instead of opening it. */
const FORWARD_DEPTH = 0.35
const DRAG_THRESHOLD = 4

/**
 * Every partner in one compact strip that scrolls sideways. Toward an edge
 * with more beyond it, partners pack tighter and smaller (see `rosterLens`),
 * so the strip reads as something you can slide through, not a cut-off row.
 */
export function PartnerRoster({
  partners,
  activeHref,
}: {
  partners: RosterPartner[]
  activeHref: string
}) {
  const stripRef = useRef<HTMLDivElement>(null)
  const frame = useRef(0)
  const dragged = useRef(false)
  const forwardedHref = useRef<string | null>(null)

  const layout = useCallback(() => {
    frame.current = 0
    const strip = stripRef.current
    if (!strip) return
    const viewport = strip.clientWidth
    const maxScroll = strip.scrollWidth - viewport
    const fade = rosterFade({ viewport, scrollLeft: strip.scrollLeft, maxScroll, zone: ZONE })
    strip.style.setProperty('--dt-roster-fade-l', `${fade.left.toFixed(1)}px`)
    strip.style.setProperty('--dt-roster-fade-r', `${fade.right.toFixed(1)}px`)
    for (const item of strip.children) {
      if (!(item instanceof HTMLElement)) continue
      const lens = rosterLens({
        center: item.offsetLeft + item.offsetWidth / 2,
        viewport,
        scrollLeft: strip.scrollLeft,
        maxScroll,
        zone: ZONE,
      })
      item.style.transform = lens.depth ? `translate3d(${lens.dx.toFixed(2)}px, 0, 0) scale(${lens.scale.toFixed(3)})` : ''
      item.style.opacity = lens.opacity < 1 ? lens.opacity.toFixed(3) : ''
      item.style.setProperty('--dt-roster-label', lens.label.toFixed(3))
      item.dataset.depth = lens.depth.toFixed(3)
    }
  }, [])
  const schedule = useCallback(() => {
    if (!frame.current) frame.current = requestAnimationFrame(layout)
  }, [layout])

  /** Scroll an item out of a stack into the flat middle of the strip. */
  const bringForward = useCallback((item: HTMLElement, behavior: ScrollBehavior) => {
    const strip = stripRef.current
    if (!strip) return
    const start = item.offsetLeft - strip.scrollLeft
    const end = start + item.offsetWidth
    if (start < ZONE) strip.scrollBy({ left: start - ZONE, behavior })
    else if (end > strip.clientWidth - ZONE) strip.scrollBy({ left: end - (strip.clientWidth - ZONE), behavior })
  }, [])

  useLayoutEffect(() => {
    const strip = stripRef.current
    if (!strip) return
    // Only a new selection moves the strip: a background refresh of the list
    // must not yank it away from where the learner slid it.
    const active = strip.querySelector<HTMLElement>('[aria-current="page"]')
    if (active && forwardedHref.current !== activeHref) {
      forwardedHref.current = activeHref
      bringForward(active, 'instant')
    }
    layout()
  }, [partners, activeHref, bringForward, layout])

  useEffect(() => {
    const strip = stripRef.current
    if (!strip) return
    // The panel mounts hidden and is sized once its category opens.
    const resize = new ResizeObserver(schedule)
    resize.observe(strip)
    // A mouse wheel only scrolls vertically; turn it sideways while the
    // roster has somewhere to go, and leave the page's scroll alone otherwise.
    const wheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return
      const maxScroll = strip.scrollWidth - strip.clientWidth
      if (maxScroll <= 0) return
      const next = Math.min(maxScroll, Math.max(0, strip.scrollLeft + event.deltaY))
      if (next === strip.scrollLeft) return
      event.preventDefault()
      strip.scrollLeft = next
    }
    strip.addEventListener('wheel', wheel, { passive: false })
    return () => {
      resize.disconnect()
      strip.removeEventListener('wheel', wheel)
      cancelAnimationFrame(frame.current)
      frame.current = 0
    }
  }, [schedule])

  // Mouse drag scrolls like a touch swipe; touch and trackpads scroll natively.
  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== 'mouse' || event.button !== 0) return
    const strip = event.currentTarget
    const origin = { x: event.clientX, scroll: strip.scrollLeft }
    dragged.current = false
    const move = (moveEvent: PointerEvent) => {
      const delta = moveEvent.clientX - origin.x
      if (!dragged.current && Math.abs(delta) < DRAG_THRESHOLD) return
      if (!dragged.current) {
        dragged.current = true
        strip.setPointerCapture(event.pointerId)
        strip.classList.add('is-dragging')
      }
      strip.scrollLeft = origin.scroll - delta
    }
    const end = () => {
      strip.removeEventListener('pointermove', move)
      strip.removeEventListener('pointerup', end)
      strip.removeEventListener('pointercancel', end)
      strip.classList.remove('is-dragging')
    }
    strip.addEventListener('pointermove', move)
    strip.addEventListener('pointerup', end)
    strip.addEventListener('pointercancel', end)
  }

  return (
    <div
      ref={stripRef}
      className="dt-partner-roster"
      onScroll={schedule}
      onPointerDown={onPointerDown}
      onClickCapture={event => {
        // The release that ends a drag is not a click on whatever is under it.
        if (!dragged.current) return
        dragged.current = false
        event.preventDefault()
        event.stopPropagation()
      }}
    >
      {partners.map(partner => {
        const href = `/partners/${encodeURIComponent(partner.partner_id)}`
        return (
          <Link
            key={partner.partner_id}
            href={href}
            prefetch={false}
            draggable={false}
            aria-label={partner.name}
            className="dt-partner-roster-item"
            aria-current={activeHref === href ? 'page' : undefined}
            onFocus={event => bringForward(event.currentTarget, 'smooth')}
            onClick={event => {
              const item = event.currentTarget
              if (Number(item.dataset.depth) < FORWARD_DEPTH) return
              event.preventDefault()
              bringForward(item, 'smooth')
            }}
          >
            <PartnerAvatar
              name={partner.name}
              emoji={partner.emoji}
              image={partner.avatar}
              color={partner.color}
              size={32}
            />
            <span>{partner.name}</span>
          </Link>
        )
      })}
    </div>
  )
}
