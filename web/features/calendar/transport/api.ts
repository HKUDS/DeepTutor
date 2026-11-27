import { apiFetch } from '@/shared/api/client'
import { scopedUrl } from '@/lib/workspace-scope'

/**
 * The calendar's wire contract (`/api/calendar`). Events and calendars are
 * the account's; `/layers` reads what the current workspace scheduled.
 *
 * Timed `start`/`end` are UTC instants (`…Z`); all-day ones are local
 * `YYYY-MM-DD` dates with an exclusive end.
 */

export type EditScope = 'this' | 'following' | 'all'
export type EventOrigin = 'user' | 'dito' | 'import'

export interface CalendarEntry {
  id: string
  /** Empty for the default calendar: the UI names it. */
  name: string
  color: string
  visible: boolean
  position: number
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface EventFields {
  calendar_id: string | null
  title: string
  notes: string
  location: string
  all_day: boolean
  start: string
  end: string
  tzid: string
  rrule: string | null
  /** Minutes before the start; all-day events may go negative (into the day). */
  reminders: number[]
  color: string | null
  task_id: string | null
  task_workspace_id: string | null
}

export type EventInput = Partial<EventFields> & Pick<EventFields, 'start' | 'end'>

export interface CalendarEvent extends Omit<EventFields, 'calendar_id'> {
  id: string
  calendar_id: string
  exdates: string[]
  series_id: string | null
  recurrence_id: string | null
  source: EventOrigin
  created_at: string
  updated_at: string
}

export interface SearchHit extends CalendarEvent {
  next_start: string | null
}

export interface Occurrence extends Omit<EventFields, 'calendar_id'> {
  reminder_times: string[]
  /** Unique per instance. */
  id: string
  /** The row to change: the series master, or the override that replaced this instance. */
  event_id: string
  series_id: string | null
  /** The instance's original start: its identity inside the series. */
  occurrence: string
  recurring: boolean
  calendar_id: string
  source: EventOrigin
}

export interface ReviewDay {
  date: string
  mastery: number
  practice: number
  paths: { id: string; title: string; count: number }[]
}

export interface AutomationRun {
  id: string
  job_id: string
  name: string
  message: string
  at: string
  kind: 'at' | 'every' | 'cron'
  expr: string | null
  every_seconds: number | null
  session_id: string | null
  enabled: boolean
}

export interface FootprintDay {
  date: string
  session_count: number
  sessions: { id: string; title: string }[]
  practice_reviews: number
  mastery_evidence: number
}

export interface CalendarLayers {
  workspace_id: string
  reviews: ReviewDay[]
  automations: AutomationRun[]
  footprints: FootprintDay[]
}

const endpoint = '/api/calendar'

export function calendarStreamUrl(): string {
  return scopedUrl(`${endpoint}/stream`)
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(`${endpoint}${path}`, {
    cache: 'no-store',
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json', ...init.headers } : init?.headers,
  })
  if (!response.ok) {
    let detail = ''
    try {
      detail = String((await response.json())?.detail ?? '')
    } catch {
      /* no body */
    }
    throw new CalendarRequestError(response.status, detail)
  }
  return response.json() as Promise<T>
}

export class CalendarRequestError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string
  ) {
    super(detail || `Calendar request failed (${status})`)
  }
}

function query(params: Record<string, string | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value != null) search.set(key, value)
  const text = search.toString()
  return text ? `?${text}` : ''
}

export function listCalendars(signal?: AbortSignal) {
  return json<{ calendars: CalendarEntry[]; revision: number }>('/calendars', { signal })
}
export function createCalendar(payload: { name: string; color: string }) {
  return json<{ calendar: CalendarEntry; revision: number }>('/calendars', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
export function updateCalendar(
  id: string,
  changes: Partial<Pick<CalendarEntry, 'name' | 'color' | 'visible' | 'position'>>
) {
  return json<{ calendar: CalendarEntry; revision: number }>(
    `/calendars/${encodeURIComponent(id)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(changes),
    }
  )
}
export function deleteCalendar(id: string) {
  return json<{ revision: number }>(`/calendars/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function listOccurrences(
  range: { start: string; end: string; tz: string },
  signal?: AbortSignal
) {
  return json<{ occurrences: Occurrence[]; revision: number }>(`/events${query(range)}`, { signal })
}
export function createEvent(input: EventInput) {
  return json<{ event: CalendarEvent; revision: number }>('/events', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
export function updateEvent(
  id: string,
  changes: Partial<EventFields>,
  options: { scope?: EditScope; occurrence?: string | null } = {}
) {
  return json<{ revision: number }>(`/events/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({
      changes,
      scope: options.scope ?? 'all',
      occurrence: options.occurrence ?? null,
    }),
  })
}
export function deleteEvent(
  id: string,
  options: { scope?: EditScope; occurrence?: string | null } = {}
) {
  return json<{ revision: number; undo_token: string }>(
    `/events/${encodeURIComponent(id)}${query({ scope: options.scope ?? 'all', occurrence: options.occurrence })}`,
    { method: 'DELETE' }
  )
}
export function searchEvents(q: string, signal?: AbortSignal) {
  return json<{ events: SearchHit[] }>(`/search${query({ q, limit: '50' })}`, { signal })
}

export function getLayers(range: { start: string; end: string; tz: string }, signal?: AbortSignal) {
  return json<CalendarLayers>(`/layers${query(range)}`, { signal })
}
export function cancelAutomation(jobId: string) {
  return json<{ ok: boolean }>(`/automations/${encodeURIComponent(jobId)}`, { method: 'DELETE' })
}

export function restoreEvent(token: string) {
  return json<{ revision: number }>(`/undo/${encodeURIComponent(token)}`, { method: 'POST' })
}

export function getTaskBlocks(signal?: AbortSignal) {
  return json<Record<string, number>>('/task-blocks', { signal })
}
