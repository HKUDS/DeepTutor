import type { EventInput, Occurrence } from '../transport/api'
import { addDays, browserTimeZone, dateKey, startOfDay } from './dates'
import { occurrenceBounds } from './items'

/**
 * An event while it is being written: dates as local `Date`s. All-day
 * drafts hold local midnights with an exclusive end, like the wire format.
 */
export interface EventDraft {
  tzid: string
  title: string
  notes: string
  location: string
  allDay: boolean
  start: Date
  end: Date
  rrule: string | null
  reminders: number[]
  color: string | null
  calendarId: string | null
  taskId: string | null
  taskWorkspaceId: string | null
}

export const DEFAULT_TIMED_REMINDERS = [10]
export const DEFAULT_ALL_DAY_REMINDERS: number[] = []

export function blankDraft(
  start: Date,
  end: Date,
  allDay: boolean,
  calendarId: string | null
): EventDraft {
  return {
    tzid: browserTimeZone(),
    title: '',
    notes: '',
    location: '',
    allDay,
    start: allDay ? startOfDay(start) : start,
    end: allDay ? startOfDay(end) : end,
    rrule: null,
    reminders: allDay ? DEFAULT_ALL_DAY_REMINDERS : DEFAULT_TIMED_REMINDERS,
    color: null,
    calendarId,
    taskId: null,
    taskWorkspaceId: null,
  }
}

export function draftFromOccurrence(occurrence: Occurrence): EventDraft {
  const { start, end } = occurrenceBounds(occurrence)
  return {
    tzid: occurrence.tzid,
    title: occurrence.title,
    notes: occurrence.notes,
    location: occurrence.location,
    allDay: occurrence.all_day,
    start,
    end,
    rrule: occurrence.rrule,
    reminders: occurrence.reminders,
    color: occurrence.color,
    calendarId: occurrence.calendar_id,
    taskId: occurrence.task_id,
    taskWorkspaceId: occurrence.task_workspace_id,
  }
}

/** Switching an event to all-day keeps its days; back to timed gives it an hour. */
export function withAllDay(draft: EventDraft, allDay: boolean): EventDraft {
  if (draft.allDay === allDay) return draft
  if (allDay) {
    const first = startOfDay(draft.start)
    const lastMoment = new Date(Math.max(draft.start.getTime(), draft.end.getTime() - 1))
    return {
      ...draft,
      allDay,
      start: first,
      end: addDays(startOfDay(lastMoment), 1),
      reminders: draft.reminders.filter(minutes => minutes >= 0),
    }
  }
  const start = new Date(
    draft.start.getFullYear(),
    draft.start.getMonth(),
    draft.start.getDate(),
    9
  )
  return {
    ...draft,
    allDay,
    start,
    end: new Date(start.getTime() + 60 * 60_000),
    reminders: draft.reminders.filter(minutes => minutes >= 0),
  }
}

export function draftToInput(draft: EventDraft): EventInput {
  return {
    calendar_id: draft.calendarId,
    title: draft.title.trim(),
    notes: draft.notes,
    location: draft.location.trim(),
    all_day: draft.allDay,
    start: draft.allDay ? dateKey(draft.start) : draft.start.toISOString(),
    end: draft.allDay ? dateKey(draft.end) : draft.end.toISOString(),
    tzid: draft.tzid,
    rrule: draft.rrule,
    reminders: draft.reminders,
    color: draft.color,
    task_id: draft.taskId,
    task_workspace_id: draft.taskWorkspaceId,
  }
}

/** The fields an edit changed, so a series only hears about what moved. */
export function draftChanges(before: EventDraft, after: EventDraft): Partial<EventInput> {
  const a = draftToInput(before)
  const b = draftToInput(after)
  const changes: Partial<EventInput> = {}
  for (const key of Object.keys(b) as (keyof EventInput)[]) {
    if (key === 'tzid') continue
    if (JSON.stringify(a[key]) !== JSON.stringify(b[key]))
      (changes as Record<string, unknown>)[key] = b[key]
  }
  // Times travel together: the server shifts a series by the start's delta.
  if ('start' in changes || 'end' in changes || 'all_day' in changes) {
    changes.start = b.start
    changes.end = b.end
    changes.all_day = b.all_day
    changes.tzid = b.tzid
  }
  return changes
}

/** An all-day draft's last day, inclusive. */
export function lastDay(draft: EventDraft): Date {
  return draft.allDay ? addDays(draft.end, -1) : draft.end
}
