'use client'

import type { CSSProperties } from 'react'
import { CalendarSearch, CalendarX2, Repeat } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  addDays,
  dateKey,
  formatDate,
  formatTime,
  formatWeekday,
  fromDateKey,
  type DateKey,
} from '../model/dates'
import {
  compareItems,
  isSpanItem,
  itemDays,
  occurrenceBounds,
  touchesDay,
  type CalendarItem,
} from '../model/items'
import type { CalendarEntry, FootprintDay, SearchHit } from '../transport/api'
import { anchorOf, type Anchor } from './AnchoredPopover'
import { itemIcon, itemTitle } from './ItemChip'

function timeLabel(
  item: CalendarItem,
  day: DateKey,
  locale: string,
  t: (key: string) => string
): string {
  if (item.allDay || isSpanItem(item)) {
    const [first, last] = itemDays(item)
    return first === last
      ? t('All day')
      : `${t('All day')} · ${formatDate(fromDateKey(first), locale, { month: 'short', day: 'numeric' })} – ${formatDate(fromDateKey(last), locale, { month: 'short', day: 'numeric' })}`
  }
  if (item.kind === 'automation') return formatTime(item.start, locale)
  const startsToday = dateKey(item.start) === day
  const endsToday = dateKey(new Date(item.end.getTime() - 1)) === day
  return `${startsToday ? formatTime(item.start, locale) : '…'} – ${endsToday ? formatTime(item.end, locale) : '…'}`
}

/** A schedule list: the days ahead that have something on them. */
export function AgendaView({
  from,
  days,
  items,
  footprints,
  now,
  selectedKey,
  onOpenItem,
  onOpenFootprint,
  onOpenDay,
}: {
  from: Date
  days: number
  items: CalendarItem[]
  footprints: Map<DateKey, FootprintDay>
  now: Date
  selectedKey: string | null
  onOpenItem: (item: CalendarItem, anchor: Anchor) => void
  onOpenFootprint: (day: FootprintDay, anchor: Anchor) => void
  onOpenDay: (day: Date) => void
}) {
  const { t, i18n } = useTranslation()
  const locale = i18n.language
  const todayKey = dateKey(now)
  const groups = Array.from({ length: days }, (_, index) => {
    const day = addDays(from, index)
    const key = dateKey(day)
    return {
      day,
      key,
      items: items.filter(item => touchesDay(item, key)).sort(compareItems),
      footprint: footprints.get(key),
    }
  }).filter(group => group.items.length || group.footprint)

  if (!groups.length)
    return (
      <div className="dt-cal-empty">
        <CalendarX2 aria-hidden size={22} strokeWidth={1.4} />
        <p>{t('Nothing scheduled in the next {{count}} days', { count: days })}</p>
      </div>
    )

  return (
    <div className="dt-cal-agenda">
      {groups.map(group => (
        <section
          key={group.key}
          className="dt-cal-agenda-day"
          data-today={group.key === todayKey || undefined}
        >
          <button type="button" className="dt-cal-agenda-date" onClick={() => onOpenDay(group.day)}>
            <span className="dt-cal-agenda-num">{group.day.getDate()}</span>
            <span className="dt-cal-agenda-meta">
              {formatDate(group.day, locale, { month: 'short' })} ·{' '}
              {formatWeekday(group.day, locale)}
            </span>
          </button>
          <ul className="dt-cal-agenda-list">
            {group.items.map(item => {
              const Icon = itemIcon(item)
              return (
                <li key={item.key}>
                  <button
                    type="button"
                    className="dt-cal-agenda-row"
                    data-selected={selectedKey === item.key || undefined}
                    data-past={item.end <= now || undefined}
                    data-done={(item.kind === 'task' && item.card.status === 'done') || undefined}
                    style={{ '--ev': item.color } as CSSProperties}
                    onClick={event => onOpenItem(item, anchorOf(event.currentTarget)!)}
                  >
                    <span className="dt-cal-agenda-time">
                      {timeLabel(item, group.key, locale, t)}
                    </span>
                    <span className="dt-cal-agenda-mark" aria-hidden>
                      {Icon ? (
                        <Icon size={13} strokeWidth={2} />
                      ) : (
                        <span className="dt-cal-chip-dot" />
                      )}
                    </span>
                    <span className="dt-cal-agenda-title">{itemTitle(item, t)}</span>
                    {item.kind === 'event' && item.occurrence.location && (
                      <span className="dt-cal-agenda-sub">{item.occurrence.location}</span>
                    )}
                  </button>
                </li>
              )
            })}
            {group.footprint && (
              <li>
                <button
                  type="button"
                  className="dt-cal-agenda-row dt-cal-agenda-footprint"
                  onClick={event =>
                    onOpenFootprint(group.footprint!, anchorOf(event.currentTarget)!)
                  }
                >
                  <span className="dt-cal-agenda-time">{t('Footprints')}</span>
                  <span className="dt-cal-agenda-mark" aria-hidden />
                  <span className="dt-cal-agenda-title">
                    {footprintSummary(group.footprint, t)}
                  </span>
                </button>
              </li>
            )}
          </ul>
        </section>
      ))}
    </div>
  )
}

export function footprintSummary(
  day: FootprintDay,
  t: (key: string, options?: Record<string, unknown>) => string
): string {
  const parts: string[] = []
  if (day.session_count) parts.push(t('{{count}} conversations', { count: day.session_count }))
  if (day.practice_reviews)
    parts.push(t('{{count}} practice reviews', { count: day.practice_reviews }))
  if (day.mastery_evidence)
    parts.push(t('{{count}} mastery checks', { count: day.mastery_evidence }))
  return parts.join(' · ')
}

/** Matches across the whole calendar, nearest first. */
export function SearchResults({
  query,
  hits,
  loading,
  calendars,
  onPick,
}: {
  query: string
  hits: SearchHit[] | null
  loading: boolean
  calendars: CalendarEntry[]
  onPick: (hit: SearchHit, anchor: Anchor) => void
}) {
  const { t, i18n } = useTranslation()
  const locale = i18n.language
  const colors = new Map(calendars.map(calendar => [calendar.id, calendar.color]))
  if (!hits || (!hits.length && !loading))
    return (
      <div className="dt-cal-empty">
        <CalendarSearch aria-hidden size={22} strokeWidth={1.4} />
        <p>{hits ? t('No events match “{{query}}”', { query }) : t('Searching…')}</p>
      </div>
    )
  return (
    <ul className="dt-cal-agenda dt-cal-search-results" aria-busy={loading}>
      {hits.map(hit => {
        const { start } = occurrenceBounds({
          all_day: hit.all_day,
          start: hit.next_start ?? hit.start,
          end: hit.end,
        })
        return (
          <li key={hit.id}>
            <button
              type="button"
              className="dt-cal-agenda-row"
              style={
                {
                  '--ev': hit.color ?? colors.get(hit.calendar_id) ?? 'var(--primary)',
                } as CSSProperties
              }
              onClick={event => onPick(hit, anchorOf(event.currentTarget)!)}
            >
              <span className="dt-cal-agenda-time">
                {formatDate(start, locale, { year: 'numeric', month: 'short', day: 'numeric' })}
                {!hit.all_day && ` · ${formatTime(start, locale)}`}
              </span>
              <span className="dt-cal-agenda-mark" aria-hidden>
                <span className="dt-cal-chip-dot" />
              </span>
              <span className="dt-cal-agenda-title">{hit.title || t('(No title)')}</span>
              {hit.location && <span className="dt-cal-agenda-sub">{hit.location}</span>}
              {hit.rrule && (
                <Repeat
                  aria-label={t('Repeats')}
                  size={12}
                  strokeWidth={1.8}
                  className="shrink-0 text-[var(--muted-foreground)]"
                />
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
