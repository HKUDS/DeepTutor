'use client'

import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { activityCalendar, type DailyUsage } from '@/lib/usage-statistics'

const colors = [
  'bg-[var(--muted)]',
  'bg-emerald-200 dark:bg-emerald-900',
  'bg-emerald-400 dark:bg-emerald-700',
  'bg-emerald-600 dark:bg-emerald-500',
  'bg-emerald-800 dark:bg-emerald-300',
]
export default function UsageActivity({
  days,
  year,
  activeDays,
  turns,
}: {
  days: readonly DailyUsage[]
  year: number
  activeDays: number
  turns: number
}) {
  const { t, i18n } = useTranslation()
  const { weeks, dates, offset } = useMemo(() => activityCalendar(days, year), [days, year])
  const [selected, setSelected] = useState<DailyUsage | null>(null)
  const [focused, setFocused] = useState(0)
  const grid = useRef<HTMLDivElement>(null)
  const max = Math.max(1, ...dates.map(day => day.turns))
  const today = new Intl.DateTimeFormat('en-CA').format(new Date())
  const dayLabel = (day: DailyUsage) =>
    t('{{date}} · {{turns}} activities · {{tokens}} tokens', {
      date: day.date,
      turns: day.turns.toLocaleString(i18n.language),
      tokens: day.tracked_turns ? day.total_tokens.toLocaleString(i18n.language) : '—',
    })
  const months = dates.flatMap((day, index) =>
    day.date.endsWith('-01')
      ? [
          {
            week: Math.floor((index + offset) / 7),
            label: new Date(`${day.date}T12:00:00Z`).toLocaleDateString(i18n.language, {
              month: 'short',
              timeZone: 'UTC',
            }),
          },
        ]
      : []
  )
  return (
    <section
      className="rounded-xl border border-[var(--border)] p-4 sm:p-5"
      aria-label={t('Usage activity')}
    >
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">{t('Usage activity')}</h2>
        <span className="text-xs text-[var(--muted-foreground)]">
          {t('{{days}} active days · {{turns}} activities', {
            days: activeDays,
            turns: turns.toLocaleString(i18n.language),
          })}
        </span>
      </div>
      <div className="overflow-x-auto pb-2" ref={grid}>
        <div style={{ minWidth: weeks.length * 14 + 28 }}>
          <div className="relative ml-7 mb-2 h-4 text-[10px] text-[var(--muted-foreground)]">
            {months.map(month => (
              <span key={month.label} className="absolute" style={{ left: month.week * 14 }}>
                {month.label}
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <div
              className="grid w-5 shrink-0 grid-rows-7 gap-[3px] text-[9px] leading-[11px] text-[var(--muted-foreground)]"
              aria-hidden="true"
            >
              {Array.from({ length: 7 }, (_, i) => (
                <span key={i}>
                  {[0, 2, 4].includes(i)
                    ? t(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][i])
                    : ''}
                </span>
              ))}
            </div>
            <div
              className="flex gap-[3px]"
              role="group"
              aria-label={t('Daily usage activity')}
            >
              {weeks.map((week, w) => (
                <div key={w} className="grid grid-rows-7 gap-[3px]">
                  {week.map((day, d) => {
                    if (!day) return <span key={d} className="h-[11px] w-[11px]" />
                    const index = w * 7 + d - offset
                    const level = day.turns
                      ? Math.min(4, Math.max(1, Math.ceil((day.turns / max) * 4)))
                      : 0
                    const future = day.date > today
                    return (
                      <button
                        key={day.date}
                        type="button"
                        data-date={day.date}
                        disabled={future}
                        tabIndex={index === focused ? 0 : -1}
                        aria-label={dayLabel(day)}
                        title={dayLabel(day)}
                        aria-pressed={selected?.date === day.date}
                        className={`h-[11px] w-[11px] rounded-[2px] outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary)] ${future ? 'bg-[var(--muted)]/40' : colors[level]} ${selected?.date === day.date ? 'ring-1 ring-[var(--foreground)] ring-offset-1 ring-offset-[var(--background)]' : ''}`}
                        onMouseEnter={() => setSelected(day)}
                        onFocus={() => {
                          setSelected(day)
                          setFocused(index)
                        }}
                        onClick={() => setSelected(day)}
                        onKeyDown={event => {
                          const moves: Record<string, number> = {
                            ArrowRight: 7,
                            ArrowLeft: -7,
                            ArrowDown: 1,
                            ArrowUp: -1,
                            Home: -index,
                            End: dates.length - 1 - index,
                          }
                          if (!(event.key in moves)) return
                          event.preventDefault()
                          let next = Math.min(
                            dates.length - 1,
                            Math.max(0, index + moves[event.key])
                          )
                          while (next > 0 && dates[next].date > today) next--
                          setFocused(next)
                          grid.current
                            ?.querySelector<HTMLButtonElement>(`[data-date="${dates[next].date}"]`)
                            ?.focus()
                        }}
                      />
                    )
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-[10px] text-[var(--muted-foreground)]">
        <p className="min-h-4" aria-live="polite">
          {selected ? dayLabel(selected) : t('Daily activity')}
        </p>
        <div className="flex items-center gap-1.5">
          <span>{t('Less activity')}</span>
          {colors.map(color => (
            <span key={color} className={`h-[10px] w-[10px] rounded-[2px] ${color}`} />
          ))}
          <span>{t('More activity')}</span>
        </div>
      </div>
    </section>
  )
}
