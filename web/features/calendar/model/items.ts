import type { TaskCard, TaskColors } from '@/lib/task-board-api'
import type {
  AutomationRun,
  CalendarEntry,
  CalendarLayers,
  FootprintDay,
  Occurrence,
  ReviewDay,
} from '../transport/api'
import {
  addDays,
  dateKey,
  daysBetween,
  fromDateKey,
  minutesIntoDay,
  MINUTES_PER_DAY,
  type DateKey,
} from './dates'

/**
 * Everything a view draws, in one shape: the account's events plus what
 * the current workspace scheduled (task due dates, reviews coming due,
 * automations). Footprints decorate days instead of occupying them.
 */

export const LAYER_COLORS = {
  review: '#0f8b6c',
  automation: '#8a5cc2',
} as const
export const DEFAULT_EVENT_COLOR = '#2f6fde'

export type LayerId = 'tasks' | 'reviews' | 'automations' | 'footprints'
export type LayerToggles = Record<LayerId, boolean>
export const DEFAULT_LAYERS: LayerToggles = {
  tasks: true,
  reviews: true,
  automations: true,
  footprints: true,
}

interface ItemBase {
  key: string
  title: string
  color: string
  allDay: boolean
  /** Timed: real instants. All-day: local midnight of the first day / exclusive end. */
  start: Date
  end: Date
}
export interface EventItem extends ItemBase {
  kind: 'event'
  occurrence: Occurrence
  calendar?: CalendarEntry
}
export interface TaskItem extends ItemBase {
  kind: 'task'
  card: TaskCard
}
export interface ReviewItem extends ItemBase {
  kind: 'review'
  day: ReviewDay
  count: number
}
export interface AutomationItem extends ItemBase {
  kind: 'automation'
  run: AutomationRun
}
export type CalendarItem = EventItem | TaskItem | ReviewItem | AutomationItem

/** Automations are moments; they take this much room in a time grid. */
export const AUTOMATION_MINUTES = 30

export function occurrenceBounds(occurrence: Pick<Occurrence, 'all_day' | 'start' | 'end'>): {
  start: Date
  end: Date
} {
  if (occurrence.all_day)
    return { start: fromDateKey(occurrence.start), end: fromDateKey(occurrence.end) }
  return { start: new Date(occurrence.start), end: new Date(occurrence.end) }
}

export function eventItem(occurrence: Occurrence, calendar: CalendarEntry | undefined): EventItem {
  const { start, end } = occurrenceBounds(occurrence)
  return {
    kind: 'event',
    key: `event:${occurrence.id}`,
    title: occurrence.title,
    color: occurrence.color ?? calendar?.color ?? DEFAULT_EVENT_COLOR,
    allDay: occurrence.all_day,
    start,
    end,
    occurrence,
    calendar,
  }
}

export function buildItems({
  occurrences,
  calendars,
  tasks,
  taskColors,
  layers,
  toggles,
}: {
  occurrences: Occurrence[]
  calendars: CalendarEntry[]
  tasks: TaskCard[]
  taskColors: TaskColors
  layers: CalendarLayers | null
  toggles: LayerToggles
}): CalendarItem[] {
  const byId = new Map(calendars.map(calendar => [calendar.id, calendar]))
  const items: CalendarItem[] = []
  for (const occurrence of occurrences) {
    const calendar = byId.get(occurrence.calendar_id)
    if (calendar && !calendar.visible) continue
    items.push(eventItem(occurrence, calendar))
  }
  if (toggles.tasks)
    for (const card of tasks) {
      if (card.archived || !card.due_date) continue
      const start = fromDateKey(card.due_date)
      items.push({
        kind: 'task',
        key: `task:${card.id}`,
        title: card.title,
        color: taskColors[card.status],
        allDay: true,
        start,
        end: addDays(start, 1),
        card,
      })
    }
  if (layers && toggles.reviews)
    for (const day of layers.reviews) {
      const count = day.mastery + day.practice
      if (!count) continue
      const start = fromDateKey(day.date)
      items.push({
        kind: 'review',
        key: `review:${day.date}`,
        title: '',
        color: LAYER_COLORS.review,
        allDay: true,
        start,
        end: addDays(start, 1),
        day,
        count,
      })
    }
  if (layers && toggles.automations)
    for (const run of layers.automations) {
      const start = new Date(run.at)
      items.push({
        kind: 'automation',
        key: `automation:${run.id}`,
        title: run.name || run.message,
        color: LAYER_COLORS.automation,
        allDay: false,
        start,
        end: new Date(start.getTime() + AUTOMATION_MINUTES * 60_000),
        run,
      })
    }
  return items
}

export function footprintsByDay(
  layers: CalendarLayers | null,
  enabled: boolean
): Map<DateKey, FootprintDay> {
  const map = new Map<DateKey, FootprintDay>()
  if (!layers || !enabled) return map
  for (const day of layers.footprints)
    if (day.session_count || day.practice_reviews || day.mastery_evidence) map.set(day.date, day)
  return map
}

/** Bars across the day row: all-day items, and timed ones lasting a day or more. */
export function isSpanItem(item: CalendarItem): boolean {
  return item.allDay || item.end.getTime() - item.start.getTime() >= MINUTES_PER_DAY * 60_000
}

/** The local days an item touches, as [first, last] inclusive keys. */
export function itemDays(item: CalendarItem): [DateKey, DateKey] {
  const first = dateKey(item.start)
  if (item.allDay) return [first, dateKey(addDays(item.end, -1))]
  // A timed item ending exactly at midnight does not touch the next day.
  const lastMoment = new Date(Math.max(item.start.getTime(), item.end.getTime() - 1))
  return [first, dateKey(lastMoment)]
}

export function touchesDay(item: CalendarItem, day: DateKey): boolean {
  const [first, last] = itemDays(item)
  return first <= day && day <= last
}

/** The part of a timed item inside one day, in wall-clock minutes since its midnight. */
export function minutesOnDay(item: CalendarItem, day: DateKey): { start: number; end: number } {
  const midnight = fromDateKey(day)
  const next = addDays(midnight, 1)
  // Wall-clock, not elapsed: on a DST day 09:00 still sits on the 9 o'clock line.
  const start = item.start <= midnight ? 0 : minutesIntoDay(item.start)
  const end = item.end >= next ? MINUTES_PER_DAY : minutesIntoDay(item.end)
  return { start, end: Math.max(end, start) }
}

/** Order inside a day list: spans first, then by start, events before layers. */
export function compareItems(a: CalendarItem, b: CalendarItem): number {
  const spanA = isSpanItem(a) ? 0 : 1
  const spanB = isSpanItem(b) ? 0 : 1
  const kind = { review: 0, task: 1, event: 2, automation: 3 }
  return (
    spanA - spanB ||
    (spanA === 0 ? kind[a.kind] - kind[b.kind] : 0) ||
    a.start.getTime() - b.start.getTime() ||
    b.end.getTime() - a.end.getTime() ||
    a.title.localeCompare(b.title)
  )
}

/** Days from `from` to an item's first day; negative when it starts earlier. */
export function dayOffset(from: DateKey, item: CalendarItem): number {
  return daysBetween(from, itemDays(item)[0])
}
