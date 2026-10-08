'use client'

import { useCallback, useEffect, useState } from 'react'
import { browserStorage } from '@/shared/storage'

const NAVIGATOR_MIN = 184
const NAVIGATOR_MAX = 400
const COMPANION_MIN = 300
const READER_MIN = 360
const HANDLE = 5
const clamp = (value: number, min: number, max: number) =>
  Math.round(Math.min(max, Math.max(min, value)))

/** Reserve the reader first; shrink side-panel floors only if the frame cannot fit them. */
export function readingPanelBounds(
  frame: number,
  navigatorOpen: boolean,
  companionOpen: boolean,
  preferredNavigator: number,
  preferredCompanion: number
) {
  const handles = (Number(navigatorOpen) + Number(companionOpen)) * HANDLE
  const available = Math.max(0, Math.floor(frame - handles - Math.min(READER_MIN, frame / 2)))
  const floors = (navigatorOpen ? NAVIGATOR_MIN : 0) + (companionOpen ? COMPANION_MIN : 0)
  const scale = floors ? Math.min(1, available / floors) : 1
  const navigatorMin = navigatorOpen ? Math.floor(NAVIGATOR_MIN * scale) : 0
  const companionMin = companionOpen ? Math.floor(COMPANION_MIN * scale) : 0
  const navigatorMax = navigatorOpen ? Math.min(NAVIGATOR_MAX, available - companionMin) : 0
  const navigatorWidth = navigatorOpen ? clamp(preferredNavigator, navigatorMin, navigatorMax) : 0
  const companionMax = companionOpen ? available - navigatorWidth : 0
  const companionWidth = companionOpen ? clamp(preferredCompanion, companionMin, companionMax) : 0
  return {
    navigatorWidth,
    companionWidth,
    navigatorMin,
    // A drag may consume free reader space, but never displaces the other panel.
    navigatorMax: navigatorOpen ? Math.min(NAVIGATOR_MAX, available - companionWidth) : 0,
    companionMin,
    companionMax,
  }
}

function readWidth(key: string, fallback: number, min: number, max: number) {
  if (typeof window === 'undefined') return fallback
  const value = Number(browserStorage.readRaw('local', key))
  return Number.isFinite(value) && value >= min && value <= max ? value : fallback
}

export function useReadingPanelLayout({
  enabled,
  navigatorOpen: preferredNavigatorOpen,
  companionOpen,
}: {
  enabled: boolean
  navigatorOpen: boolean
  companionOpen: boolean
}) {
  const [element, gridRef] = useState<HTMLDivElement | null>(null)
  const [frame, setFrame] = useState(0)
  const [navigatorWidth, setNavigatorWidth] = useState(() =>
    readWidth('dt.reader.navigatorWidth', 210, NAVIGATOR_MIN, NAVIGATOR_MAX)
  )
  const [companionWidth, setCompanionWidth] = useState(() =>
    readWidth('dt.reader.companionWidth', 380, COMPANION_MIN, 2400)
  )
  const [focus, setFocus] = useState<{ width?: number } | null>(null)
  const companionFocus = focus !== null && enabled && companionOpen
  const navigatorOpen = companionFocus ? false : preferredNavigatorOpen

  // A callback ref also observes a grid that appears after the loading screen.
  useEffect(() => {
    if (!element) return
    const measure = () => setFrame(element.clientWidth)
    const scheduled = requestAnimationFrame(measure)
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure)
    observer?.observe(element)
    if (!observer) window.addEventListener("resize", measure)
    return () => {
      cancelAnimationFrame(scheduled)
      observer?.disconnect()
      if (!observer) window.removeEventListener("resize", measure)
    }
  }, [element])

  const bounds = readingPanelBounds(
    frame,
    navigatorOpen,
    companionOpen,
    navigatorWidth,
    companionFocus ? (focus.width ?? frame / 2) : companionWidth
  )
  const exitFocus = useCallback(() => setFocus(null), [])
  const toggleFocus = useCallback(() => setFocus(current => (current ? null : {})), [])
  const resizeNavigator = (width: number) => {
    setNavigatorWidth(width)
    browserStorage.writeRaw('local', 'dt.reader.navigatorWidth', String(width))
  }
  const resizeCompanion = (width: number) => {
    if (companionFocus) {
      setFocus({ width })
    } else {
      setCompanionWidth(width)
      browserStorage.writeRaw('local', 'dt.reader.companionWidth', String(width))
    }
  }
  const measured = enabled && frame > 0
  const gridTemplateColumns = measured
    ? [
        ...(navigatorOpen ? [`${bounds.navigatorWidth}px`, `${HANDLE}px`] : []),
        'minmax(0,1fr)',
        ...(companionOpen ? [`${HANDLE}px`, `${bounds.companionWidth}px`] : []),
      ].join(' ')
    : undefined

  return {
    ...bounds,
    gridRef,
    gridStyle: gridTemplateColumns ? { gridTemplateColumns } : undefined,
    navigatorOpen,
    showNavigatorHandle: measured && navigatorOpen,
    showCompanionHandle: measured && companionOpen,
    companionFocus,
    toggleFocus,
    exitFocus,
    resizeNavigator,
    resizeCompanion,
  }
}
