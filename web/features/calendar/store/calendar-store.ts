'use client'

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
  calendarStreamUrl,
  getLayers,
  getTaskBlocks,
  listCalendars,
  listOccurrences,
  type CalendarEntry,
  type CalendarLayers,
  type Occurrence,
} from '../transport/api'

/**
 * The calendar's live state. One account revision counter, kept current by
 * the `/stream` events and by every mutation's response, drives refetches;
 * the calendars list is shared, while each view fetches its own range.
 */

let generation = 0
let revision = 0
let calendars: CalendarEntry[] | null = null
let calendarsError = false
let loadedRevision = -1
let loading: Promise<void> | undefined
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach(listener => listener())
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Record a revision the server reported; newer ones trigger refetches. */
export function noteCalendarRevision(next: number) {
  if (next <= revision) return
  revision = next
  emit()
}

export function refreshCalendars(): Promise<void> {
  if (loading) return loading
  const currentGeneration = generation
  loading = (async () => {
    let received = false
    try {
      const response = await listCalendars()
      if (generation !== currentGeneration) return
      calendars = [...response.calendars].sort(
        (a, b) => a.position - b.position || a.created_at.localeCompare(b.created_at)
      )
      calendarsError = false
      loadedRevision = response.revision
      revision = Math.max(revision, response.revision)
      received = true
    } catch {
      if (generation !== currentGeneration) return
      calendarsError = true
    } finally {
      if (generation === currentGeneration) {
        loading = undefined
        emit()
        // A mutation/stream update may have overtaken this in-flight response.
        if (received && loadedRevision < revision && owners > 0) void refreshCalendars()
      }
    }
  })()
  return loading
}

let owners = 0
let stop: (() => void) | undefined

/** One stream per tab, shared by the page and the reminder runtime. */
export function startCalendarSync(): () => void {
  if (++owners === 1) {
    const source =
      typeof EventSource !== 'undefined'
        ? new EventSource(calendarStreamUrl(), { withCredentials: true })
        : null
    let fallback: ReturnType<typeof setInterval> | undefined
    const poll = () => {
      if (!document.hidden) void refreshCalendars()
    }
    if (source) {
      source.onmessage = event => {
        try {
          noteCalendarRevision(Number(JSON.parse(event.data).revision) || 0)
        } catch {
          poll()
        }
      }
      source.onerror = () => {
        fallback ??= setInterval(poll, 15_000)
      }
      source.onopen = () => {
        clearInterval(fallback)
        fallback = undefined
      }
    } else fallback = setInterval(poll, 15_000)
    window.addEventListener('focus', poll)
    stop = () => {
      source?.close()
      clearInterval(fallback)
      window.removeEventListener('focus', poll)
    }
  }
  return () => {
    if (--owners === 0) {
      stop?.()
      stop = undefined
      generation++
      revision = 0
      calendars = null
      calendarsError = false
      loadedRevision = -1
      loading = undefined
      emit()
    }
  }
}

export function useCalendarRevision(): number {
  return useSyncExternalStore(
    subscribe,
    () => revision,
    () => 0
  )
}

export function useCalendars(): { calendars: CalendarEntry[] | null; error: boolean } {
  const current = useCalendarRevision()
  const snapshot = useSyncExternalStore(
    subscribe,
    () => calendars,
    () => null
  )
  const error = useSyncExternalStore(
    subscribe,
    () => calendarsError,
    () => false
  )
  useEffect(() => {
    if (loadedRevision < current || calendars === null) void refreshCalendars()
  }, [current])
  return { calendars: snapshot, error }
}

export interface CalendarRange {
  start: string
  end: string
  tz: string
}

/** A view's instances; the previous range stays on screen while the next loads. */
export function useOccurrences(range: CalendarRange) {
  const current = useCalendarRevision()
  const [state, setState] = useState<{
    key: string
    occurrences: Occurrence[]
    revision: number
  } | null>(null)
  const [error, setError] = useState(false)
  const key = `${range.start}|${range.end}|${range.tz}`
  const [nonce, setNonce] = useState(0)
  const loaded = useRef<{ key: string; revision: number; nonce: number } | null>(null)
  useEffect(() => {
    // A response already as new as the account revision needs no second fetch.
    const last = loaded.current
    if (last && last.key === key && last.revision >= current && last.nonce === nonce) return
    const controller = new AbortController()
    listOccurrences(range, controller.signal)
      .then(response => {
        if (controller.signal.aborted) return
        loaded.current = { key, revision: response.revision, nonce }
        setState({ key, occurrences: response.occurrences, revision: response.revision })
        setError(false)
        noteCalendarRevision(response.revision)
      })
      .catch(reason => {
        if (!controller.signal.aborted) setError(Boolean(reason))
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the key spells out the range
  }, [key, current, nonce])
  const retry = useCallback(() => setNonce(value => value + 1), [])
  return {
    occurrences: state?.occurrences ?? null,
    revision: state?.revision ?? -1,
    stale: state !== null && state.key !== key,
    error,
    retry,
  }
}

/** What the current workspace scheduled; refreshed on focus and every few minutes. */
export function useLayers(range: CalendarRange, workspaceId: string, enabled: boolean) {
  const [error, setError] = useState(false)
  const [layers, setLayers] = useState<CalendarLayers | null>(null)
  const [nonce, setNonce] = useState(0)
  const key = `${range.start}|${range.end}|${range.tz}|${workspaceId}`
  const keyRef = useRef(key)
  keyRef.current = key
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    getLayers(range, controller.signal)
      .then(response => {
        if (!controller.signal.aborted && keyRef.current === key) {
          setLayers(response)
          setError(false)
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true)
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the key spells out the range
  }, [key, enabled, nonce])
  useEffect(() => {
    if (!enabled) return
    const refresh = () => {
      if (!document.hidden) setNonce(value => value + 1)
    }
    const timer = setInterval(refresh, 180_000)
    window.addEventListener('focus', refresh)
    return () => {
      clearInterval(timer)
      window.removeEventListener('focus', refresh)
    }
  }, [enabled])
  const reload = useCallback(() => setNonce(value => value + 1), [])
  return { layers: layers && layers.workspace_id === workspaceId ? layers : null, reload, error }
}

export function useTaskBlocks(workspaceId: string) {
  const revision = useCalendarRevision()
  const [state, setState] = useState<{
    workspaceId: string
    counts: Record<string, number>
  } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    getTaskBlocks(controller.signal)
      .then(counts => {
        if (!controller.signal.aborted) setState({ workspaceId, counts })
      })
      .catch(() => {})
    return () => controller.abort()
  }, [workspaceId, revision])
  return state?.workspaceId === workspaceId ? state.counts : {}
}
