'use client'

import { useLayoutEffect, useState, type ReactNode } from 'react'
import { ArrowDownUp, Check, ChevronDown, Search, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { formatRelativeTime, getDayGroupKey, type DayGroupKey } from '@/lib/relative-time'
import { browserStorage } from '@/shared/storage'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import Tooltip from '@/shared/ui/Tooltip'

export type RecordSort = 'updatedAt' | 'createdAt'

const GROUP_LABELS: Record<DayGroupKey, string> = {
  today: 'Today',
  this_week: 'Within a week',
  earlier: 'Earlier',
}
const PAGE = 30

/**
 * View state of one sidebar record list: order (remembered per list), the
 * search term and how far the list has been expanded.
 */
export function useRecordView(storageKey: string) {
  const [sort, setSortState] = useState<RecordSort>('updatedAt')
  const [query, setQueryState] = useState('')
  const [searching, setSearching] = useState(false)
  const [limit, setLimit] = useState(PAGE)
  useLayoutEffect(() => {
    if (browserStorage.readRaw('local', storageKey) === 'createdAt') {
      // Restore the view preference before paint, without changing any record.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSortState('createdAt')
    }
  }, [storageKey])
  return {
    sort,
    query,
    searching,
    limit,
    setSort(value: RecordSort) {
      setSortState(value)
      setLimit(PAGE)
      browserStorage.writeRaw('local', storageKey, value)
    },
    setQuery(value: string) {
      setQueryState(value)
      setLimit(PAGE)
    },
    setSearching(open: boolean) {
      setSearching(open)
      if (!open) setQueryState('')
    },
    more: () => setLimit(value => value + PAGE),
  }
}
export type RecordView = ReturnType<typeof useRecordView>

/** Rows newest first under Today / Within a week / Earlier. */
export function groupByDay<T>(rows: readonly T[], time: (row: T) => number) {
  return [...Map.groupBy(rows, row => getDayGroupKey(time(row)))]
}

export const dayGroupLabel = (group: DayGroupKey) => GROUP_LABELS[group]

/** One list's title with its order and search controls on the right. */
export function RecordHeader({
  title,
  count,
  view,
  searchLabel,
  sorts = ['updatedAt', 'createdAt'],
}: {
  title: string
  count?: number
  view: RecordView
  searchLabel: string
  sorts?: RecordSort[]
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const rootRef = useMenuPopover<HTMLDivElement>(open, setOpen)
  const close = () => view.setSearching(false)
  return (
    <div className="dt-record-header">
      <div className="dt-navigation-heading">
        <h2>
          {title}
          {count !== undefined && <span className="dt-navigation-count">{count}</span>}
        </h2>
        <div className="dt-navigation-actions">
          {sorts.length > 1 && (
            <div ref={rootRef} className="relative">
              <Tooltip label={t('navigation.sortRecords')} suppressed={open}>
                <button
                  type="button"
                  className="dt-nav-icon"
                  aria-label={t('navigation.sortRecords')}
                  aria-haspopup="menu"
                  aria-expanded={open}
                  onClick={() => setOpen(value => !value)}
                >
                  <ArrowDownUp size={14} strokeWidth={1.7} />
                </button>
              </Tooltip>
              {open && (
                <div role="menu" aria-label={t('navigation.sortRecords')} className="dt-popover dt-record-sort-menu">
                  <div className="dt-menu-label">{t('navigation.sortRecords')}</div>
                  {sorts.map(value => (
                    <button
                      key={value}
                      type="button"
                      role="menuitemradio"
                      aria-checked={view.sort === value}
                      className="dt-menu-item"
                      onClick={() => {
                        view.setSort(value)
                        setOpen(false)
                      }}
                    >
                      <span className="min-w-0 flex-1">
                        {t(value === 'updatedAt' ? 'navigation.lastActive' : 'navigation.createdTime')}
                      </span>
                      {view.sort === value && <Check size={14} strokeWidth={2} />}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          <Tooltip label={searchLabel}>
            <button
              type="button"
              className={`dt-nav-icon ${view.searching ? 'is-active' : ''}`}
              aria-label={searchLabel}
              aria-expanded={view.searching}
              onClick={() => view.setSearching(!view.searching)}
            >
              <Search size={14} strokeWidth={1.7} />
            </button>
          </Tooltip>
        </div>
      </div>
      {view.searching && (
        <label className="dt-record-search">
          <Search size={13} strokeWidth={1.7} aria-hidden />
          <input
            autoFocus
            type="search"
            aria-label={searchLabel}
            placeholder={searchLabel}
            value={view.query}
            onChange={event => view.setQuery(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Escape') close()
            }}
          />
          <button type="button" aria-label={t('navigation.clearSearch')} onClick={close}>
            <X size={13} strokeWidth={1.8} />
          </button>
        </label>
      )}
    </div>
  )
}

/** Relative time at the right edge of a record row; the exact time on hover. */
export function RecordTime({ seconds, className = '' }: { seconds: number; className?: string }) {
  const { i18n } = useTranslation()
  return (
    <time
      className={`dt-record-time ${className}`}
      dateTime={new Date(seconds * 1000).toISOString()}
      title={new Date(seconds * 1000).toLocaleString(i18n.language)}
    >
      {formatRelativeTime(seconds, i18n.language)}
    </time>
  )
}

/** Day groups, an empty state and "Show more", shared by every record list. */
export function RecordGroups<T>({
  rows,
  view,
  time,
  renderRow,
  lead,
  empty,
}: {
  rows: readonly T[]
  view: RecordView
  time: (row: T) => number
  renderRow: (row: T) => ReactNode
  /** Rows shown above the day groups regardless of time (pinned ones). */
  lead?: { label: string; rows: readonly T[] }
  empty?: ReactNode
}) {
  const { t } = useTranslation()
  const shown = rows.slice(0, view.limit)
  return (
    <>
      {lead && lead.rows.length > 0 && (
        <section className="dt-record-group">
          <h2>{lead.label}</h2>
          {lead.rows.map(renderRow)}
        </section>
      )}
      {groupByDay(shown, time).map(([group, items]) => (
        <section className="dt-record-group" key={group}>
          <h2>{t(dayGroupLabel(group))}</h2>
          {items.map(renderRow)}
        </section>
      ))}
      {!rows.length && !lead?.rows.length && empty}
      {rows.length > view.limit && (
        <button type="button" className="dt-navigation-row w-full" onClick={view.more}>
          <ChevronDown size={15} />
          {t('Show more')}
        </button>
      )}
    </>
  )
}
