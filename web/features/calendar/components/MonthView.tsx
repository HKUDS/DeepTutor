'use client'

import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { useTranslation } from 'react-i18next'
import {
  addDays,
  dateKey,
  daysBetween,
  formatDate,
  formatWeekday,
  fromDateKey,
  type DateKey,
} from '../model/dates'
import {
  compareItems,
  isSpanItem,
  itemDays,
  type CalendarItem,
  type EventItem,
} from '../model/items'
import { packLanes } from '../model/layout'
import type { FootprintDay } from '../transport/api'
import { anchorOf, type Anchor } from './AnchoredPopover'
import { dayAtPoint, startGesture } from './gesture'
import { ItemChip } from './ItemChip'
import { TASK_DRAG_TYPE, readTaskDrag, writeTaskDrag } from './task-drag'
import { FootprintButton, type GridDraft } from './TimeGrid'

const LANE = 21
const HEAD = 28

type Drag =
  | { kind: 'create'; from: DateKey; to: DateKey }
  | { kind: 'move'; item: EventItem; grab: DateKey; day: DateKey }

/**
 * The month as weeks of cells. Spans run across cells as bars, timed items
 * sit on their first day as one line each; whatever does not fit a cell
 * folds into "+N more".
 */
export function MonthView({
  weeks,
  month,
  items,
  footprints,
  now,
  draft,
  selectedKey,
  onCreate,
  onOpenItem,
  onOpenFootprint,
  onOpenDay,
  onShowMore,
  onReschedule,
  onDropTask,
}: {
  weeks: Date[][]
  month: number
  items: CalendarItem[]
  footprints: Map<DateKey, FootprintDay>
  now: Date
  draft: GridDraft | null
  selectedKey: string | null
  onCreate: (draft: GridDraft, anchor: Anchor) => void
  onOpenItem: (item: CalendarItem, anchor: Anchor) => void
  onOpenFootprint: (day: FootprintDay, anchor: Anchor) => void
  onOpenDay: (day: Date) => void
  onShowMore: (day: Date, items: CalendarItem[], anchor: Anchor) => void
  onReschedule: (item: EventItem, start: Date, end: Date) => void
  onDropTask: (taskId: string, target: GridDraft) => void
}) {
  const { t, i18n } = useTranslation()
  const locale = i18n.language
  const bodyRef = useRef<HTMLDivElement>(null)
  const [lanes, setLanes] = useState(4)
  const [drag, setDrag] = useState<Drag | null>(null)
  const dragRef = useRef<Drag | null>(null)
  const [dropDay, setDropDay] = useState<DateKey | null>(null)
  const todayKey = dateKey(now)

  useLayoutEffect(() => {
    const node = bodyRef.current
    if (!node) return
    const measure = () => {
      const rowHeight = node.clientHeight / Math.max(1, weeks.length)
      setLanes(Math.max(1, Math.floor((rowHeight - HEAD - 4) / LANE)))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [weeks.length])

  const shown = useMemo(() => {
    if (drag?.kind !== 'move') return items
    const shift = daysBetween(drag.grab, drag.day)
    return items.map(item =>
      item.key === drag.item.key
        ? { ...item, start: addDays(item.start, shift), end: addDays(item.end, shift) }
        : item
    )
  }, [items, drag])

  const ghost = useMemo((): [DateKey, DateKey] | null => {
    if (drag?.kind === 'create')
      return drag.from <= drag.to ? [drag.from, drag.to] : [drag.to, drag.from]
    if (draft)
      return [dateKey(draft.start), dateKey(draft.allDay ? addDays(draft.end, -1) : draft.start)]
    return null
  }, [drag, draft])

  const set = (next: Drag | null) => {
    dragRef.current = next
    setDrag(next)
  }

  const beginCreate = (event: ReactPointerEvent, day: DateKey) => {
    startGesture(event, {
      onStart: () => set({ kind: 'create', from: day, to: day }),
      onMove: (x, y) => {
        const over = dayAtPoint(x, y)
        const current = dragRef.current
        if (over && current?.kind === 'create') set({ ...current, to: over })
      },
      onClick: () => {
        const start = fromDateKey(day)
        onCreate({ start, end: addDays(start, 1), allDay: true }, cellAnchor(day, day))
      },
      onDrop: () => {
        const current = dragRef.current
        if (current?.kind !== 'create') return
        const [from, to] =
          current.from <= current.to ? [current.from, current.to] : [current.to, current.from]
        onCreate(
          { start: fromDateKey(from), end: addDays(fromDateKey(to), 1), allDay: true },
          cellAnchor(from, to)
        )
      },
      onEnd: () => set(null),
    })
  }

  const beginMove = (event: ReactPointerEvent<HTMLElement>, item: CalendarItem) => {
    if (item.kind !== 'event') return
    event.stopPropagation()
    const target = event.currentTarget
    const grab = dayAtPoint(event.clientX, event.clientY) ?? dateKey(item.start)
    startGesture(event, {
      onStart: () => set({ kind: 'move', item, grab, day: grab }),
      onMove: (x, y) => {
        const over = dayAtPoint(x, y)
        const current = dragRef.current
        if (over && current?.kind === 'move') set({ ...current, day: over })
      },
      onClick: () => onOpenItem(item, anchorOf(target)!),
      onDrop: () => {
        const current = dragRef.current
        if (current?.kind !== 'move') return
        const shift = daysBetween(current.grab, current.day)
        if (shift) onReschedule(item, addDays(item.start, shift), addDays(item.end, shift))
      },
      onEnd: () => set(null),
    })
  }

  const cellAnchor = (from: DateKey, to: DateKey): Anchor => {
    const first = bodyRef.current
      ?.querySelector<HTMLElement>(`[data-cal-day="${from}"]`)
      ?.getBoundingClientRect()
    const last =
      bodyRef.current
        ?.querySelector<HTMLElement>(`[data-cal-day="${to}"]`)
        ?.getBoundingClientRect() ?? first
    if (!first || !last) return { top: 120, left: 200, right: 200, bottom: 160 }
    return { top: first.top, left: first.left, right: last.right, bottom: last.bottom }
  }

  const taskOver = (event: DragEvent<HTMLElement>, day: DateKey) => {
    if (!event.dataTransfer.types.includes(TASK_DRAG_TYPE)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
    setDropDay(day)
  }
  const taskDropped = (event: DragEvent<HTMLElement>, day: DateKey) => {
    setDropDay(null)
    const id = readTaskDrag(event.dataTransfer)
    if (!id) return
    event.preventDefault()
    const start = fromDateKey(day)
    onDropTask(id, { start, end: addDays(start, 1), allDay: true })
  }

  return (
    <div className="dt-cal-month">
      <div className="dt-cal-month-head">
        {weeks[0]?.map(day => (
          <div key={day.getDay()}>{formatWeekday(day, locale)}</div>
        ))}
      </div>
      <div
        ref={bodyRef}
        className="dt-cal-month-body"
        style={{ gridTemplateRows: `repeat(${weeks.length}, minmax(0, 1fr))` }}
      >
        {weeks.map(week => (
          <MonthWeek
            key={dateKey(week[0])}
            week={week}
            month={month}
            items={shown}
            lanes={lanes}
            footprints={footprints}
            todayKey={todayKey}
            now={now}
            ghost={ghost}
            dropDay={dropDay}
            selectedKey={selectedKey}
            dragKey={drag?.kind === 'move' ? drag.item.key : null}
            onPointerDownCell={beginCreate}
            onPointerDownItem={beginMove}
            onOpenItem={onOpenItem}
            onOpenFootprint={onOpenFootprint}
            onOpenDay={onOpenDay}
            onShowMore={onShowMore}
            onTaskOver={taskOver}
            onTaskLeave={() => setDropDay(null)}
            onTaskDrop={taskDropped}
            moreLabel={count => t('{{count}} more', { count })}
          />
        ))}
      </div>
    </div>
  )
}

function MonthWeek({
  week,
  month,
  items,
  lanes,
  footprints,
  todayKey,
  now,
  ghost,
  dropDay,
  selectedKey,
  dragKey,
  onPointerDownCell,
  onPointerDownItem,
  onOpenItem,
  onOpenFootprint,
  onOpenDay,
  onShowMore,
  onTaskOver,
  onTaskLeave,
  onTaskDrop,
  moreLabel,
}: {
  week: Date[]
  month: number
  items: CalendarItem[]
  lanes: number
  footprints: Map<DateKey, FootprintDay>
  todayKey: DateKey
  now: Date
  ghost: [DateKey, DateKey] | null
  dropDay: DateKey | null
  selectedKey: string | null
  dragKey: string | null
  onPointerDownCell: (event: ReactPointerEvent, day: DateKey) => void
  onPointerDownItem: (event: ReactPointerEvent<HTMLElement>, item: CalendarItem) => void
  onOpenItem: (item: CalendarItem, anchor: Anchor) => void
  onOpenFootprint: (day: FootprintDay, anchor: Anchor) => void
  onOpenDay: (day: Date) => void
  onShowMore: (day: Date, items: CalendarItem[], anchor: Anchor) => void
  onTaskOver: (event: DragEvent<HTMLElement>, day: DateKey) => void
  onTaskLeave: () => void
  onTaskDrop: (event: DragEvent<HTMLElement>, day: DateKey) => void
  moreLabel: (count: number) => string
}) {
  const { i18n: weekI18n } = useTranslation()
  const weekLocale = weekI18n.language
  const keys = week.map(dateKey)
  const first = keys[0]
  const last = keys[6]

  const layout = useMemo(() => {
    const inWeek = items
      .map(item => {
        const [a, b] = itemDays(item)
        // Timed items that are not spans live on their first day only.
        const lastDay = isSpanItem(item) ? b : a
        return { item, a, b: lastDay }
      })
      .filter(({ a, b }) => a <= last && b >= first)
      .sort((x, y) => compareItems(x.item, y.item))
    const placed = packLanes(
      inWeek.map(({ item, a, b }, order) => ({
        id: item.key,
        first: Math.max(0, daysBetween(first, a)),
        last: Math.min(6, daysBetween(first, b)),
        order,
      }))
    )
    const byKey = new Map(inWeek.map(entry => [entry.item.key, entry.item]))
    const perDay = keys.map((_, index) =>
      placed.filter(place => place.first <= index && index <= place.last)
    )
    const overflowing = perDay.map(list => list.length > lanes)
    const visible = placed.filter(place => {
      if (place.lane < lanes - 1) return true
      if (place.lane > lanes - 1) return false
      for (let index = place.first; index <= place.last; index++)
        if (overflowing[index]) return false
      return true
    })
    return { visible, byKey, perDay, overflowing }
  }, [items, keys, first, last, lanes])

  const ghostSpan =
    ghost && ghost[0] <= last && ghost[1] >= first
      ? {
          first: Math.max(0, daysBetween(first, ghost[0])),
          last: Math.min(6, daysBetween(first, ghost[1])),
        }
      : null

  return (
    <div className="dt-cal-week">
      {week.map((day, index) => {
        const key = keys[index]
        const footprint = footprints.get(key)
        return (
          <div
            key={key}
            data-cal-day={key}
            className="dt-cal-cell"
            data-outside={day.getMonth() !== month || undefined}
            data-today={key === todayKey || undefined}
            data-drop={dropDay === key || undefined}
            onPointerDown={event => {
              if ((event.target as HTMLElement).closest('[data-cal-item], button')) return
              onPointerDownCell(event, key)
            }}
            onDragOver={event => onTaskOver(event, key)}
            onDragLeave={event => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onTaskLeave()
            }}
            onDrop={event => onTaskDrop(event, key)}
          >
            <div className="dt-cal-cell-head">
              <button type="button" className="dt-cal-cell-date" onClick={() => onOpenDay(day)}>
                {day.getDate() === 1
                  ? formatDate(day, weekLocale, {
                      month: 'short',
                      day: 'numeric',
                    })
                  : day.getDate()}
              </button>
              {footprint && <FootprintButton day={footprint} onOpen={onOpenFootprint} />}
            </div>
            {layout.overflowing[index] && (
              <button
                type="button"
                className="dt-cal-more"
                style={{ top: HEAD + (lanes - 1) * LANE }}
                onClick={event => {
                  const dayItems = layout.perDay[index]
                    .map(place => layout.byKey.get(place.id)!)
                    .sort(compareItems)
                  onShowMore(
                    day,
                    dayItems,
                    anchorOf(event.currentTarget.closest('[data-cal-day]'))!
                  )
                }}
              >
                {moreLabel(layout.perDay[index].length - (lanes - 1))}
              </button>
            )}
          </div>
        )
      })}
      {ghostSpan && (
        <div
          className="dt-cal-ghost dt-cal-ghost-span"
          style={laneStyle(ghostSpan.first, ghostSpan.last, 0)}
        />
      )}
      {layout.visible.map(place => {
        const item = layout.byKey.get(place.id)!
        const span = isSpanItem(item)
        const [a, b] = itemDays(item)
        return (
          <ItemChip
            key={item.key}
            data-cal-item
            item={item}
            variant={span ? 'span' : 'line'}
            selected={selectedKey === item.key || dragKey === item.key}
            past={item.end <= now}
            continuesBefore={span && a < first}
            continuesAfter={span && b > last}
            style={laneStyle(place.first, place.last, place.lane)}
            draggable={item.kind === 'task'}
            onDragStart={event => {
              if (item.kind === 'task') writeTaskDrag(event.dataTransfer, item.card.id)
            }}
            onPointerDown={event => onPointerDownItem(event, item)}
            onClick={event => {
              if (item.kind !== 'event') onOpenItem(item, anchorOf(event.currentTarget)!)
            }}
          />
        )
      })}
    </div>
  )
}

function laneStyle(first: number, last: number, lane: number): CSSProperties {
  return {
    position: 'absolute',
    top: HEAD + lane * LANE,
    height: LANE - 2,
    left: `calc(${(first / 7) * 100}% + 3px)`,
    width: `calc(${((last - first + 1) / 7) * 100}% - 6px)`,
  }
}
