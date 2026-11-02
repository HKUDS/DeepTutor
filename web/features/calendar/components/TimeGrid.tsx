'use client'

import {
  createElement,
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import Tooltip from '@/shared/ui/Tooltip'
import { useTranslation } from 'react-i18next'
import {
  addDays,
  atMinutes,
  clamp,
  dateKey,
  daysBetween,
  formatHour,
  formatTime,
  formatWeekday,
  fromDateKey,
  minutesIntoDay,
  MINUTES_PER_DAY,
  type DateKey,
} from '../model/dates'
import {
  compareItems,
  isSpanItem,
  itemDays,
  minutesOnDay,
  touchesDay,
  type CalendarItem,
  type EventItem,
} from '../model/items'
import { layoutDay, packLanes } from '../model/layout'
import type { FootprintDay } from '../transport/api'
import { anchorOf, type Anchor } from './AnchoredPopover'
import { ItemChip, itemIcon, itemTitle } from './ItemChip'
import { footprintSummary } from './AgendaView'
import { TASK_DRAG_TYPE, readTaskDrag, writeTaskDrag } from './task-drag'

const HOUR = 48
const SNAP = 15
const LANE = 22
const DRAG_THRESHOLD = 4

export interface GridDraft {
  start: Date
  end: Date
  allDay: boolean
}

type Drag =
  | { kind: 'create'; day: DateKey; from: number; to: number }
  | { kind: 'move'; item: EventItem; grab: number; start: Date }
  | { kind: 'resize'; item: EventItem; end: Date }
  | { kind: 'span-create'; from: DateKey; to: DateKey }
  | { kind: 'span-move'; item: EventItem; grabDay: DateKey; day: DateKey }

function snapDate(date: Date): Date {
  const minutes = minutesIntoDay(date)
  const snapped = Math.round(minutes / SNAP) * SNAP
  return atMinutes(fromDateKey(dateKey(date)), snapped)
}

export function TimeGrid({
  days,
  items,
  footprints,
  now,
  draft,
  selectedKey,
  onCreate,
  onOpenItem,
  onOpenFootprint,
  onReschedule,
  onDropTask,
  onOpenDay,
}: {
  days: Date[]
  items: CalendarItem[]
  footprints: Map<DateKey, FootprintDay>
  now: Date
  /** The event being created, drawn as a ghost until it is saved or dropped. */
  draft: GridDraft | null
  selectedKey: string | null
  onCreate: (draft: GridDraft, anchor: Anchor) => void
  onOpenItem: (item: CalendarItem, anchor: Anchor) => void
  onOpenFootprint: (day: FootprintDay, anchor: Anchor) => void
  onReschedule: (item: EventItem, start: Date, end: Date) => void
  onDropTask: (taskId: string, target: GridDraft) => void
  onOpenDay: (day: Date) => void
}) {
  const { t, i18n } = useTranslation()
  const locale = i18n.language
  const scrollRef = useRef<HTMLDivElement>(null)
  const columnsRef = useRef<HTMLDivElement>(null)
  const spanRowRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const dragRef = useRef<Drag | null>(null)
  const [taskDrop, setTaskDrop] = useState<
    { day: DateKey; minutes: number } | { day: DateKey; allDay: true } | null
  >(null)
  const keys = useMemo(() => days.map(dateKey), [days])
  const todayKey = dateKey(now)

  // Open on the working day, or a little above "now" when today is shown.
  const scrolledFor = useRef<string | null>(null)
  useLayoutEffect(() => {
    const node = scrollRef.current
    const key = keys.join()
    if (!node || scrolledFor.current === key) return
    scrolledFor.current = key
    const focus = keys.includes(todayKey) ? Math.max(0, minutesIntoDay(now) - 120) : 7 * 60 + 30
    node.scrollTop = (Math.min(focus, 7 * 60 + 30) / 60) * HOUR
  }, [keys, now, todayKey])

  /* ---- Geometry ------------------------------------------------------- */

  const columnAt = useCallback((clientX: number): { key: DateKey; rect: DOMRect } | null => {
    const columns = [...(columnsRef.current?.querySelectorAll<HTMLElement>('[data-cal-col]') ?? [])]
    if (!columns.length) return null
    let best = columns[0]
    for (const column of columns) {
      const rect = column.getBoundingClientRect()
      if (clientX >= rect.left) best = column
    }
    return { key: best.dataset.calCol as DateKey, rect: best.getBoundingClientRect() }
  }, [])
  const minutesAt = (clientY: number, rect: DOMRect) =>
    clamp(((clientY - rect.top) / HOUR) * 60, 0, MINUTES_PER_DAY)
  const spanDayAt = useCallback(
    (clientX: number): DateKey | null => {
      const row = spanRowRef.current
      if (!row) return null
      const rect = row.getBoundingClientRect()
      const index = clamp(
        Math.floor(((clientX - rect.left) / rect.width) * keys.length),
        0,
        keys.length - 1
      )
      return keys[index] ?? null
    },
    [keys]
  )

  /* ---- Pointer drags (window-level so a fast pointer never escapes) --- */

  const autoScroll = useRef<number | null>(null)
  const lastPointer = useRef<{ x: number; y: number } | null>(null)

  const update = useCallback((next: Drag | null) => {
    dragRef.current = next
    setDrag(next)
  }, [])

  const track = useCallback(
    (clientX: number, clientY: number) => {
      const current = dragRef.current
      if (!current) return
      if (current.kind === 'span-create' || current.kind === 'span-move') {
        const day = spanDayAt(clientX)
        if (!day) return
        update(current.kind === 'span-create' ? { ...current, to: day } : { ...current, day })
        return
      }
      const column = columnAt(clientX)
      if (!column) return
      const minutes = minutesAt(clientY, column.rect)
      if (current.kind === 'create') {
        update({ ...current, to: Math.round(minutes / SNAP) * SNAP })
      } else if (current.kind === 'move') {
        const pointer = atMinutes(fromDateKey(column.key), minutes)
        update({ ...current, start: snapDate(new Date(pointer.getTime() - current.grab)) })
      } else if (current.kind === 'resize') {
        const end = snapDate(atMinutes(fromDateKey(column.key), minutes))
        const minEnd = current.item.start.getTime() + SNAP * 60_000
        update({ ...current, end: new Date(Math.max(end.getTime(), minEnd)) })
      }
    },
    [columnAt, spanDayAt, update]
  )

  const beginPointer = useCallback(
    (
      event: ReactPointerEvent,
      start: Drag,
      onClick: (anchor: Anchor | null) => void,
      onDrop: (drag: Drag, anchor: Anchor | null) => void
    ) => {
      if (event.button !== 0) return
      event.preventDefault()
      const origin = { x: event.clientX, y: event.clientY }
      const target = event.currentTarget as HTMLElement
      let moved = false
      const move = (pointer: PointerEvent) => {
        lastPointer.current = { x: pointer.clientX, y: pointer.clientY }
        if (
          !moved &&
          Math.hypot(pointer.clientX - origin.x, pointer.clientY - origin.y) < DRAG_THRESHOLD
        )
          return
        if (!moved) {
          moved = true
          update(start)
          document.body.dataset.calendarDragging = start.kind
        }
        track(pointer.clientX, pointer.clientY)
      }
      const finish = (commit: boolean) => {
        window.removeEventListener('pointermove', move)
        window.removeEventListener('pointerup', up)
        window.removeEventListener('pointercancel', cancel)
        window.removeEventListener('keydown', escape)
        delete document.body.dataset.calendarDragging
        if (autoScroll.current) cancelAnimationFrame(autoScroll.current)
        autoScroll.current = null
        lastPointer.current = null
        const final = dragRef.current
        update(null)
        if (!commit) return
        if (!moved) onClick(anchorOf(target))
        else if (final) onDrop(final, null)
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
      const scroll = () => {
        const node = scrollRef.current
        const pointer = lastPointer.current
        if (
          node &&
          pointer &&
          moved &&
          dragRef.current &&
          !dragRef.current.kind.startsWith('span')
        ) {
          const rect = node.getBoundingClientRect()
          const edge = 36
          const delta = pointer.y < rect.top + edge ? -10 : pointer.y > rect.bottom - edge ? 10 : 0
          if (delta) {
            node.scrollTop += delta
            track(pointer.x, pointer.y)
          }
        }
        autoScroll.current = requestAnimationFrame(scroll)
      }
      autoScroll.current = requestAnimationFrame(scroll)
    },
    [track, update]
  )

  /* ---- What to draw: the drag's preview replaces the original --------- */

  const shown = useMemo(() => {
    if (!drag || (drag.kind !== 'move' && drag.kind !== 'resize' && drag.kind !== 'span-move'))
      return items
    return items.map(item => {
      if (item.key !== drag.item.key) return item
      if (drag.kind === 'move') {
        const length = item.end.getTime() - item.start.getTime()
        return { ...item, start: drag.start, end: new Date(drag.start.getTime() + length) }
      }
      if (drag.kind === 'resize') return { ...item, end: drag.end }
      const shift = daysBetween(drag.grabDay, drag.day)
      return { ...item, start: addDays(item.start, shift), end: addDays(item.end, shift) }
    })
  }, [items, drag])

  const spans = useMemo(() => {
    const first = keys[0]
    const last = keys[keys.length - 1]
    const list = shown
      .filter(item => isSpanItem(item))
      .filter(item => {
        const [a, b] = itemDays(item)
        return a <= last && b >= first
      })
    if (draft?.allDay) {
      const ghost = {
        key: 'draft',
        start: draft.start,
        end: draft.end,
        allDay: true,
      } as CalendarItem
      list.push(ghost)
    }
    if (drag?.kind === 'span-create') {
      const [from, to] = drag.from <= drag.to ? [drag.from, drag.to] : [drag.to, drag.from]
      list.push({
        key: 'draft',
        start: fromDateKey(from),
        end: addDays(fromDateKey(to), 1),
        allDay: true,
      } as CalendarItem)
    }
    const placed = packLanes(
      list.map((item, order) => {
        const [a, b] = itemDays(item)
        return {
          id: item.key,
          first: Math.max(0, daysBetween(first, a)),
          last: Math.min(keys.length - 1, daysBetween(first, b)),
          order: item.key === 'draft' ? -1 : order,
        }
      })
    )
    const byKey = new Map(list.map(item => [item.key, item]))
    return placed.map(place => ({ place, item: byKey.get(place.id)! }))
  }, [shown, keys, draft, drag])
  const laneCount = spans.reduce((max, { place }) => Math.max(max, place.lane + 1), 0)

  const columns = useMemo(
    () =>
      keys.map(key => {
        const timed = shown
          .filter(item => !isSpanItem(item) && touchesDay(item, key))
          .sort(compareItems)
        const byKey = new Map(timed.map(item => [item.key, item]))
        const boxes = timed.map(item => ({ id: item.key, ...minutesOnDay(item, key) }))
        if (draft && !draft.allDay && dateKey(draft.start) === key)
          boxes.push({
            id: 'draft',
            start: minutesIntoDay(draft.start),
            end: minutesIntoDay(draft.end) || MINUTES_PER_DAY,
          })
        if (drag?.kind === 'create' && drag.day === key) {
          const [from, to] = drag.from <= drag.to ? [drag.from, drag.to] : [drag.to, drag.from]
          boxes.push({ id: 'draft', start: from, end: Math.max(to, from + SNAP) })
        }
        return { key, placed: layoutDay(boxes), byKey }
      }),
    [keys, shown, draft, drag]
  )

  /* ---- Gestures ---------------------------------------------------------- */

  const startCreate = (event: ReactPointerEvent<HTMLDivElement>, key: DateKey) => {
    if ((event.target as HTMLElement).closest('[data-cal-item]')) return
    const rect = event.currentTarget.getBoundingClientRect()
    const minutes = minutesAt(event.clientY, rect)
    const from = Math.floor(minutes / SNAP) * SNAP
    beginPointer(
      event,
      { kind: 'create', day: key, from, to: from + SNAP },
      () => {
        // A click opens an hour on the half hour it landed in.
        const slot = Math.floor(minutes / 30) * 30
        const day = fromDateKey(key)
        const start = atMinutes(day, Math.min(slot, MINUTES_PER_DAY - 60))
        const end = new Date(start.getTime() + 60 * 60_000)
        onCreate(
          { start, end, allDay: false },
          anchorFor(key, minutesIntoDay(start), minutesIntoDay(end))
        )
      },
      final => {
        if (final.kind !== 'create') return
        const [a, b] = final.from <= final.to ? [final.from, final.to] : [final.to, final.from]
        const day = fromDateKey(final.day)
        const end = Math.max(b, a + SNAP)
        onCreate(
          { start: atMinutes(day, a), end: atMinutes(day, end), allDay: false },
          anchorFor(final.day, a, end)
        )
      }
    )
  }

  const anchorFor = (key: DateKey, from: number, to: number): Anchor => {
    const column = columnsRef.current?.querySelector<HTMLElement>(`[data-cal-col="${key}"]`)
    const rect = column?.getBoundingClientRect()
    if (!rect) return { top: 120, left: 200, right: 200, bottom: 160 }
    return {
      top: rect.top + (from / 60) * HOUR,
      bottom: rect.top + (to / 60) * HOUR,
      left: rect.left,
      right: rect.right,
    }
  }

  const startItem = (
    event: ReactPointerEvent<HTMLElement>,
    item: CalendarItem,
    mode: 'move' | 'resize',
    segmentDay: DateKey
  ) => {
    if (item.kind !== 'event') return
    event.stopPropagation()
    const column = columnAt(event.clientX)
    const pointer = column
      ? atMinutes(fromDateKey(segmentDay), minutesAt(event.clientY, column.rect))
      : item.start
    beginPointer(
      event,
      mode === 'move'
        ? { kind: 'move', item, grab: pointer.getTime() - item.start.getTime(), start: item.start }
        : { kind: 'resize', item, end: item.end },
      anchor => anchor && onOpenItem(item, anchor),
      final => {
        if (final.kind === 'move') {
          const length = item.end.getTime() - item.start.getTime()
          if (final.start.getTime() !== item.start.getTime())
            onReschedule(item, final.start, new Date(final.start.getTime() + length))
        } else if (final.kind === 'resize' && final.end.getTime() !== item.end.getTime())
          onReschedule(item, item.start, final.end)
      }
    )
  }

  const startSpan = (event: ReactPointerEvent<HTMLElement>, item: CalendarItem | null) => {
    const day = spanDayAt(event.clientX)
    if (!day) return
    if (item) {
      if (item.kind !== 'event') return
      event.stopPropagation()
      beginPointer(
        event,
        { kind: 'span-move', item, grabDay: day, day },
        anchor => anchor && onOpenItem(item, anchor),
        final => {
          if (final.kind !== 'span-move') return
          const shift = daysBetween(final.grabDay, final.day)
          if (shift) onReschedule(item, addDays(item.start, shift), addDays(item.end, shift))
        }
      )
      return
    }
    beginPointer(
      event,
      { kind: 'span-create', from: day, to: day },
      () => {
        const start = fromDateKey(day)
        onCreate({ start, end: addDays(start, 1), allDay: true }, spanAnchor(day, day))
      },
      final => {
        if (final.kind !== 'span-create') return
        const [from, to] = final.from <= final.to ? [final.from, final.to] : [final.to, final.from]
        onCreate(
          { start: fromDateKey(from), end: addDays(fromDateKey(to), 1), allDay: true },
          spanAnchor(from, to)
        )
      }
    )
  }

  const spanAnchor = (from: DateKey, to: DateKey): Anchor => {
    const rect = spanRowRef.current?.getBoundingClientRect()
    if (!rect) return { top: 120, left: 200, right: 200, bottom: 160 }
    const width = rect.width / keys.length
    const a = Math.max(0, keys.indexOf(from))
    const b = Math.max(a, keys.indexOf(to))
    return {
      top: rect.top,
      bottom: rect.bottom,
      left: rect.left + a * width,
      right: rect.left + (b + 1) * width,
    }
  }

  /* ---- Tasks dragged in from the rail, the board or the day row ------- */

  const taskOver = (event: DragEvent<HTMLElement>, key: DateKey, allDay: boolean) => {
    if (!event.dataTransfer.types.includes(TASK_DRAG_TYPE)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
    if (allDay) setTaskDrop({ day: key, allDay: true })
    else {
      const rect = event.currentTarget.getBoundingClientRect()
      setTaskDrop({ day: key, minutes: Math.floor(minutesAt(event.clientY, rect) / SNAP) * SNAP })
    }
  }
  const taskDropped = (event: DragEvent<HTMLElement>, key: DateKey, allDay: boolean) => {
    const id = readTaskDrag(event.dataTransfer)
    setTaskDrop(null)
    if (!id) return
    event.preventDefault()
    const day = fromDateKey(key)
    if (allDay) onDropTask(id, { start: day, end: addDays(day, 1), allDay: true })
    else {
      const rect = event.currentTarget.getBoundingClientRect()
      const minutes = Math.min(
        Math.floor(minutesAt(event.clientY, rect) / SNAP) * SNAP,
        MINUTES_PER_DAY - 60
      )
      const start = atMinutes(day, minutes)
      onDropTask(id, { start, end: new Date(start.getTime() + 60 * 60_000), allDay: false })
    }
  }

  /* ---- Render ------------------------------------------------------------ */

  const gridColumns = {
    gridTemplateColumns: `repeat(${keys.length}, minmax(0, 1fr))`,
  } as CSSProperties
  const nowMinutes = minutesIntoDay(now)

  return (
    <div className="dt-cal-timegrid" data-days={keys.length}>
      <div className="dt-cal-grid-head">
        <div className="dt-cal-gutter" />
        <div className="dt-cal-day-heads" style={gridColumns}>
          {days.map((day, index) => {
            const key = keys[index]
            const footprint = footprints.get(key)
            return (
              <div key={key} className="dt-cal-day-head" data-today={key === todayKey || undefined}>
                <button type="button" className="dt-cal-day-label" onClick={() => onOpenDay(day)}>
                  <span className="dt-cal-weekday">{formatWeekday(day, locale)}</span>
                  <span className="dt-cal-daynum">{day.getDate()}</span>
                </button>
                {footprint && <FootprintButton day={footprint} onOpen={onOpenFootprint} />}
              </div>
            )
          })}
        </div>
      </div>

      <div className="dt-cal-span-row">
        <div className="dt-cal-gutter dt-cal-span-label">{t('All day')}</div>
        <div
          ref={spanRowRef}
          className="dt-cal-span-area"
          style={{ ...gridColumns, minHeight: Math.max(1, laneCount) * LANE + 8 }}
          onPointerDown={event => {
            if ((event.target as HTMLElement).closest('[data-cal-item]')) return
            startSpan(event, null)
          }}
        >
          {keys.map(key => (
            <div
              key={key}
              data-cal-day={key}
              className="dt-cal-span-cell"
              data-drop={(taskDrop && 'allDay' in taskDrop && taskDrop.day === key) || undefined}
              onDragOver={event => taskOver(event, key, true)}
              onDragLeave={() => setTaskDrop(null)}
              onDrop={event => taskDropped(event, key, true)}
            />
          ))}
          {spans.map(({ place, item }) =>
            item.key === 'draft' ? (
              <div
                key="draft"
                className="dt-cal-ghost dt-cal-ghost-span"
                style={spanStyle(place.first, place.last, place.lane, keys.length)}
              />
            ) : (
              <ItemChip
                key={item.key}
                data-cal-item
                item={item}
                variant="span"
                selected={
                  selectedKey === item.key ||
                  (drag?.kind === 'span-move' && drag.item.key === item.key)
                }
                past={item.end <= now}
                continuesBefore={itemDays(item)[0] < keys[0]}
                continuesAfter={itemDays(item)[1] > keys[keys.length - 1]}
                style={spanStyle(place.first, place.last, place.lane, keys.length)}
                draggable={item.kind === 'task'}
                onDragStart={event => {
                  if (item.kind === 'task') writeTaskDrag(event.dataTransfer, item.card.id)
                }}
                onPointerDown={event => {
                  if (item.kind === 'event') startSpan(event, item)
                }}
                onClick={event => {
                  if (item.kind !== 'event') onOpenItem(item, anchorOf(event.currentTarget)!)
                }}
              />
            )
          )}
        </div>
      </div>

      <div ref={scrollRef} className="dt-cal-scroll">
        <div className="dt-cal-body" style={{ height: 24 * HOUR }}>
          <div className="dt-cal-gutter dt-cal-hours" aria-hidden>
            {Array.from({ length: 23 }, (_, index) => {
              // The current time takes the gutter where it would collide with an hour.
              const hidden =
                keys.includes(todayKey) && Math.abs((index + 1) * 60 - nowMinutes) < 15
              return (
                <span key={index} style={{ top: (index + 1) * HOUR }} data-hidden={hidden || undefined}>
                  {formatHour(index + 1, locale)}
                </span>
              )
            })}
            {keys.includes(todayKey) && (
              <span className="dt-cal-now-label" style={{ top: (nowMinutes / 60) * HOUR }}>
                {formatTime(now, locale)}
              </span>
            )}
          </div>
          <div ref={columnsRef} className="dt-cal-columns" style={gridColumns}>
            {columns.map(({ key, placed, byKey }) => (
              <div
                key={key}
                data-cal-col={key}
                className="dt-cal-column"
                data-today={key === todayKey || undefined}
                onPointerDown={event => startCreate(event, key)}
                onDragOver={event => taskOver(event, key, false)}
                onDragLeave={event => {
                  if (!event.currentTarget.contains(event.relatedTarget as Node | null))
                    setTaskDrop(null)
                }}
                onDrop={event => taskDropped(event, key, false)}
              >
                {placed.map(box => {
                  const top = (box.start / 60) * HOUR
                  const height = Math.max(((box.end - box.start) / 60) * HOUR, 18)
                  const style = {
                    top,
                    height,
                    left: `calc(${box.left * 100}% + 1px)`,
                    width: `calc(${box.width * 100}% - ${box.left + box.width >= 0.999 ? 6 : 3}px)`,
                  }
                  if (box.id === 'draft')
                    return <div key="draft" className="dt-cal-ghost" style={style} />
                  const item = byKey.get(box.id)!
                  const segmentEnds = item.end.getTime() <= addDays(fromDateKey(key), 1).getTime()
                  return (
                    <TimedBlock
                      key={item.key}
                      item={item}
                      style={style}
                      compact={height < 34}
                      selected={
                        selectedKey === item.key ||
                        (drag?.kind !== 'create' &&
                          drag !== null &&
                          'item' in drag &&
                          drag.item.key === item.key)
                      }
                      past={item.end <= now}
                      resizable={item.kind === 'event' && segmentEnds}
                      onPointerDown={(event, mode) => startItem(event, item, mode, key)}
                      onOpen={anchor => onOpenItem(item, anchor)}
                    />
                  )
                })}
                {taskDrop && !('allDay' in taskDrop) && taskDrop.day === key && (
                  <div
                    className="dt-cal-ghost"
                    style={{ top: (taskDrop.minutes / 60) * HOUR, height: HOUR, left: 1, right: 6 }}
                  />
                )}
                {key === todayKey && (
                  <div
                    aria-hidden
                    className="dt-cal-now"
                    style={{ top: (nowMinutes / 60) * HOUR }}
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function spanStyle(first: number, last: number, lane: number, count: number): CSSProperties {
  return {
    position: 'absolute',
    top: 4 + lane * LANE,
    height: LANE - 3,
    left: `calc(${(first / count) * 100}% + 2px)`,
    width: `calc(${((last - first + 1) / count) * 100}% - 5px)`,
  }
}

function TimedBlock({
  item,
  style,
  compact,
  selected,
  past,
  resizable,
  onPointerDown,
  onOpen,
}: {
  item: CalendarItem
  style: CSSProperties
  compact: boolean
  selected: boolean
  past: boolean
  resizable: boolean
  onPointerDown: (event: ReactPointerEvent<HTMLElement>, mode: 'move' | 'resize') => void
  onOpen: (anchor: Anchor) => void
}) {
  const { t, i18n } = useTranslation()
  const Icon = itemIcon(item)
  const time = `${formatTime(item.start, i18n.language)} – ${formatTime(item.end, i18n.language)}`
  const done = item.kind === 'task' && item.card.status === 'done'
  return (
    <div
      data-cal-item
      data-kind={item.kind}
      data-selected={selected || undefined}
      data-past={past || undefined}
      data-done={done || undefined}
      data-compact={compact || undefined}
      className="dt-cal-block"
      style={{ ...style, '--ev': item.color } as CSSProperties}
      onPointerDown={event => onPointerDown(event, 'move')}
    >
      <button
        type="button"
        className="dt-cal-block-body"
        aria-label={`${itemTitle(item, t)}, ${item.kind === 'automation' ? formatTime(item.start, i18n.language) : time}`}
        onClick={event => {
          // Events open from the pointer gesture; this path is for keyboards.
          if (event.detail === 0 || item.kind !== 'event') onOpen(anchorOf(event.currentTarget)!)
        }}
      >
        <span className="dt-cal-block-title">
          {Icon &&
            createElement(Icon, {
              'aria-hidden': true,
              size: 12,
              strokeWidth: 2,
              className: 'dt-cal-chip-icon',
            })}
          {itemTitle(item, t)}
          {compact && item.kind !== 'automation' && (
            <span className="dt-cal-block-time">{formatTime(item.start, i18n.language)}</span>
          )}
        </span>
        {!compact && item.kind !== 'automation' && (
          <span className="dt-cal-block-time">{time}</span>
        )}
        {!compact && item.kind === 'event' && item.occurrence.location && (
          <span className="dt-cal-block-time">{item.occurrence.location}</span>
        )}
      </button>
      {resizable && (
        <span
          aria-hidden
          className="dt-cal-resize"
          onPointerDown={event => {
            event.stopPropagation()
            onPointerDown(event, 'resize')
          }}
        />
      )}
    </div>
  )
}

/** A day's learning activity, as one quiet mark: the deeper the tint, the
 * more happened. The details are a click away. */
export function FootprintButton({
  day,
  onOpen,
}: {
  day: FootprintDay
  onOpen: (day: FootprintDay, anchor: Anchor) => void
}) {
  const { t } = useTranslation()
  const total = day.session_count + day.practice_reviews + day.mastery_evidence
  const level = total >= 12 ? 4 : total >= 6 ? 3 : total >= 2 ? 2 : 1
  const summary = footprintSummary(day, t)
  return (
    <Tooltip label={t('Learning footprints')} description={summary}>
      <button
        type="button"
        aria-label={`${t('Learning footprints')}: ${summary}`}
        className="dt-cal-footprint"
        data-level={level}
        onClick={event => onOpen(day, anchorOf(event.currentTarget)!)}
      >
        <i aria-hidden />
      </button>
    </Tooltip>
  )
}
