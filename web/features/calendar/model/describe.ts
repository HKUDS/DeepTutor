import { addDays, dateKey, formatDate, formatTime } from './dates'

type Translate = (key: string, options?: Record<string, unknown>) => string

/**
 * Reminder offsets are minutes before the start. All-day events start at
 * midnight, so their offsets read as a clock time: -540 is 09:00 on the
 * day, 900 is 09:00 the day before.
 */
export const TIMED_REMINDERS = [0, 5, 10, 15, 30, 60, 120, 1440, 2880, 10080]
export const ALL_DAY_REMINDERS = [-540, 900, 2340, 9540]

function clockAfterMidnight(minutes: number, locale: string): string {
  return formatTime(new Date(2000, 0, 1, 0, minutes), locale)
}

export function describeReminder(
  minutes: number,
  allDay: boolean,
  locale: string,
  t: Translate
): string {
  if (allDay) {
    if (minutes <= 0)
      return t('On the day at {{time}}', { time: clockAfterMidnight(-minutes, locale) })
    const days = Math.ceil(minutes / 1440)
    const time = clockAfterMidnight(days * 1440 - minutes, locale)
    return days === 1
      ? t('The day before at {{time}}', { time })
      : t('{{count}} days before at {{time}}', { count: days, time })
  }
  if (minutes === 0) return t('At the start time')
  if (minutes % 10080 === 0) return t('{{count}} weeks before', { count: minutes / 10080 })
  if (minutes % 1440 === 0) return t('{{count}} days before', { count: minutes / 1440 })
  if (minutes % 60 === 0) return t('{{count}} hours before', { count: minutes / 60 })
  return t('{{count}} minutes before', { count: minutes })
}

/** "Sat, Oct 17 · 09:00 – 10:00", "Oct 17 – 19", "Oct 17 22:00 – Oct 18 01:00". */
export function describeWhen(start: Date, end: Date, allDay: boolean, locale: string): string {
  const day = (date: Date) =>
    formatDate(date, locale, { month: 'short', day: 'numeric', weekday: 'short' })
  if (allDay) {
    const last = addDays(end, -1)
    return dateKey(last) <= dateKey(start) ? day(start) : `${day(start)} – ${day(last)}`
  }
  const lastMoment = new Date(Math.max(start.getTime(), end.getTime() - 1))
  if (dateKey(lastMoment) === dateKey(start))
    return `${day(start)} · ${formatTime(start, locale)} – ${formatTime(end, locale)}`
  return `${day(start)} ${formatTime(start, locale)} – ${day(end)} ${formatTime(end, locale)}`
}

export function describeEvery(seconds: number, t: Translate): string {
  if (seconds % 86400 === 0) return t('Every {{count}} days', { count: seconds / 86400 })
  if (seconds % 3600 === 0) return t('Every {{count}} hours', { count: seconds / 3600 })
  return t('Every {{count}} minutes', { count: Math.max(1, Math.round(seconds / 60)) })
}
