'use client'

import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Tooltip from '@/shared/ui/Tooltip'
import {
  addMonths,
  dateKey,
  daysBetween,
  formatDate,
  formatMonthTitle,
  formatWeekday,
  monthWeeks,
  startOfMonth,
} from '../model/dates'

/** A small month to jump around in; the shown range is shaded. */
export function MiniMonth({
  cursor,
  range,
  weekStart,
  today,
  onPick,
}: {
  cursor: Date
  range: [string, string]
  weekStart: number
  today: Date
  onPick: (day: Date) => void
}) {
  const narrow = daysBetween(range[0], range[1]) <= 7
  const { t, i18n } = useTranslation()
  const locale = i18n.language
  const [shown, setShown] = useState(() => startOfMonth(cursor))
  const [followed, setFollowed] = useState(dateKey(startOfMonth(cursor)))
  // Follow the main view when it leaves the month on display.
  const cursorMonth = dateKey(startOfMonth(cursor))
  if (cursorMonth !== followed) {
    setFollowed(cursorMonth)
    setShown(startOfMonth(cursor))
  }
  const weeks = monthWeeks(shown, weekStart)
  const todayKey = dateKey(today)
  return (
    <div className="dt-cal-mini">
      <div className="dt-cal-mini-head">
        <span className="dt-cal-mini-title">{formatMonthTitle(shown, locale)}</span>
        <Tooltip label={t('Previous month')}>
          <button
            type="button"
            aria-label={t('Previous month')}
            className="dt-cal-icon-button"
            onClick={() => setShown(month => addMonths(month, -1))}
          >
            <ChevronLeft size={15} strokeWidth={1.8} />
          </button>
        </Tooltip>
        <Tooltip label={t('Next month')}>
          <button
            type="button"
            aria-label={t('Next month')}
            className="dt-cal-icon-button"
            onClick={() => setShown(month => addMonths(month, 1))}
          >
            <ChevronRight size={15} strokeWidth={1.8} />
          </button>
        </Tooltip>
      </div>
      <div className="dt-cal-mini-grid" role="grid" aria-label={formatMonthTitle(shown, locale)}>
        <div role="row" className="dt-cal-mini-row">
          {weeks[0].map(day => (
            <span key={day.getDay()} role="columnheader" className="dt-cal-mini-weekday">
              {formatWeekday(day, locale, 'narrow')}
            </span>
          ))}
        </div>
        {weeks.map(week => (
          <div key={dateKey(week[0])} role="row" className="dt-cal-mini-row">
            {week.map(day => {
              const key = dateKey(day)
              // Shading a whole month in a month picker says nothing; mark a week or a day.
              const inRange = narrow && key >= range[0] && key < range[1]
              return (
                <button
                  key={key}
                  type="button"
                  role="gridcell"
                  aria-label={formatDate(day, locale, {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                  })}
                  aria-current={key === todayKey ? 'date' : undefined}
                  data-outside={day.getMonth() !== shown.getMonth() || undefined}
                  data-in-range={inRange || undefined}
                  className="dt-cal-mini-day"
                  onClick={() => onPick(day)}
                >
                  {day.getDate()}
                </button>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
