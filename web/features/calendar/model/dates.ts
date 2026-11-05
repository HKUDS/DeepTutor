import {
  addDays as addCalendarDays,
  addMonths as addCalendarMonths,
  startOfDay as calendarDayStart,
} from 'date-fns'

import { JALALI_MONTHS, jalaliMonthLength, jalaliToIso, persianDigits, toJalali } from '@/lib/jalali'

/**
 * Calendar date arithmetic on native `Date` in the browser's own zone.
 *
 * A calendar day is a plain `YYYY-MM-DD` key, never a UTC instant: an
 * all-day item stored as midnight UTC lands on the previous day for anyone
 * east of Greenwich before their 8 a.m. Days are built from their parts
 * (`new Date(y, m, d + n)`), so a DST day keeps its real 23 or 25 hours and
 * wall-clock times survive the shift.
 */

export type DateKey = string

export const MINUTES_PER_DAY = 24 * 60

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

export function dateKey(date: Date): DateKey {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** Local midnight of a `YYYY-MM-DD` key. */
export function fromDateKey(key: DateKey): Date {
  const [year, month, day] = key.split('-').map(Number)
  return new Date(year, month - 1, day)
}

export function startOfDay(date: Date): Date {
  return calendarDayStart(date)
}

/** The same wall-clock time `days` later. */
export function addDays(date: Date, days: number): Date {
  return addCalendarDays(date, days)
}

export function addDaysToKey(key: DateKey, days: number): DateKey {
  return dateKey(addDays(fromDateKey(key), days))
}

/** Months later, clamped to the last day: Jan 31 + 1 month is Feb 28/29. */
export function addMonths(date: Date, months: number): Date {
  return addCalendarMonths(date, months)
}

export function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

export function startOfWeek(date: Date, weekStartsOn: number): Date {
  const day = startOfDay(date)
  const offset = (day.getDay() - weekStartsOn + 7) % 7
  return addDays(day, -offset)
}

export function isSameDay(a: Date, b: Date): boolean {
  return dateKey(a) === dateKey(b)
}

/** Whole calendar days from `a` to `b`, immune to DST-length days. */
export function daysBetween(a: DateKey, b: DateKey): number {
  const [ay, am, ad] = a.split('-').map(Number)
  const [by, bm, bd] = b.split('-').map(Number)
  return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86_400_000)
}

/** Wall-clock minutes since local midnight (0–1439). */
export function minutesIntoDay(date: Date): number {
  return date.getHours() * 60 + date.getMinutes()
}

/** `minutes` of wall-clock time on `day`; 1440 is the next midnight. */
export function atMinutes(day: Date, minutes: number): Date {
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, minutes)
}

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

/** First day of the week for a locale: Sunday in the US, Monday by default. */
export function weekStartsOn(locale: string): number {
  // Persian readers expect Saturday first, which Intl reports as day 6
  // (Monday 1 … Sunday 7) → Date 6 % 7 = 6.
  if (isPersian(locale)) return 6
  try {
    const info = new Intl.Locale(locale) as Intl.Locale & {
      getWeekInfo?: () => { firstDay: number }
      weekInfo?: { firstDay: number }
    }
    const firstDay = info.getWeekInfo?.().firstDay ?? info.weekInfo?.firstDay
    // Intl numbers Monday 1 … Sunday 7; Date numbers Sunday 0.
    if (firstDay) return firstDay % 7
  } catch {
    /* fall through to the region heuristic */
  }
  return /^en(-US)?$/i.test(locale) ? 0 : 1
}

/** Whether the interface language is Persian, so dates render Jalali. */
export function isPersian(locale: string): boolean {
  return (locale || '').split('-')[0] === 'fa'
}

/**
 * Whether a month cursor moves by Jalali (not Gregorian) months for this
 * locale. The calendar grid, its title and its navigation must all agree.
 */
export function monthsAreJalali(locale: string): boolean {
  return isPersian(locale)
}

/**
 * The same wall-clock time, `months` Jalali months later. Jalali months are
 * 29–31 days and their lengths differ from Gregorian ones, so the target is
 * reached through the Jalali calendar and then mapped back onto the Gregorian
 * day whose local midnight represents it.
 */
export function addJalaliMonths(date: Date, months: number): Date {
  const j = toJalali(date.getFullYear(), date.getMonth() + 1, date.getDate())
  const total = (j.jy * 12 + (j.jm - 1)) + months
  const year = Math.floor(total / 12)
  const month = (total % 12 + 12) % 12 + 1
  const day = Math.min(j.jd, jalaliMonthLength(year, month))
  const iso = jalaliToIso(year, month, day)
  const [gy, gm, gd] = iso.split('-').map(Number)
  return new Date(gy, gm - 1, gd, date.getHours(), date.getMinutes())
}

/** The Jalali month the cursor falls in, as `[firstDay, lastDay]` ISO keys. */
export function jalaliMonthBounds(cursor: Date): [DateKey, DateKey] {
  const j = toJalali(cursor.getFullYear(), cursor.getMonth() + 1, cursor.getDate())
  const len = jalaliMonthLength(j.jy, j.jm)
  return [jalaliToIso(j.jy, j.jm, 1), jalaliToIso(j.jy, j.jm, len)]
}

/** First day of the Jalali month the cursor falls in, at local midnight. */
export function startOfJalaliMonth(cursor: Date): Date {
  const [first] = jalaliMonthBounds(cursor)
  return fromDateKey(first)
}

/** The Jalali month title, e.g. "آبان ۱۴۰۵" — month first, then the year. */
export function formatJalaliMonthTitle(cursor: Date): string {
  const j = toJalali(cursor.getFullYear(), cursor.getMonth() + 1, cursor.getDate())
  return `${JALALI_MONTHS[j.jm - 1]} ${persianDigits(j.jy)}`
}

/** A full Jalali date, e.g. «۱۲ آبان ۱۴۰۵» — for the calendar heading. */
export function formatJalaliFullDate(cursor: Date): string {
  const j = toJalali(cursor.getFullYear(), cursor.getMonth() + 1, cursor.getDate())
  return `${persianDigits(j.jd)} ${JALALI_MONTHS[j.jm - 1]} ${persianDigits(j.jy)}`
}

/**
 * A Jalali week span, e.g. «۱۲ – ۱۸ آبان ۱۴۰۵». When the week crosses a month
 * boundary both months are named ("۳۰ مهر – ۶ آبان ۱۴۰۵") so the heading never
 * implies a seven-day run inside one month that does not exist.
 */
export function formatJalaliWeekTitle(from: Date, to: Date): string {
  const a = toJalali(from.getFullYear(), from.getMonth() + 1, from.getDate())
  const b = toJalali(to.getFullYear(), to.getMonth() + 1, to.getDate())
  const ys = persianDigits(a.jy)
  if (a.jm === b.jm) {
    return `${persianDigits(a.jd)} – ${persianDigits(b.jd)} ${JALALI_MONTHS[a.jm - 1]} ${ys}`
  }
  return `${persianDigits(a.jd)} ${JALALI_MONTHS[a.jm - 1]} – ${persianDigits(b.jd)} ${
    JALALI_MONTHS[b.jm - 1]
  } ${ys}`
}

/**
 * The weeks a month spans, each seven days long, starting on `weekStart`.
 * In Persian the month is a Jalali month, so the grid covers 1..29/30/31 of
 * that month with the neighbouring days borrowed from the Jalali neighbours.
 */
export function monthWeeks(cursor: Date, weekStart: number, locale?: string): Date[][] {
  if (locale && isPersian(locale)) return jalaliMonthWeeks(cursor, weekStart)
  const first = startOfWeek(startOfMonth(cursor), weekStart)
  const nextMonth = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1)
  const weeks: Date[][] = []
  for (let start = first; start < nextMonth; start = addDays(start, 7)) {
    weeks.push(Array.from({ length: 7 }, (_, index) => addDays(start, index)))
  }
  return weeks
}

/** Weeks of a Jalali month: leading/trailing days come from its neighbours. */
function jalaliMonthWeeks(cursor: Date, weekStart: number): Date[][] {
  const [firstIso, lastIso] = jalaliMonthBounds(cursor)
  const gridStart = startOfWeek(fromDateKey(firstIso), weekStart)
  const gridEnd = addDays(startOfWeek(fromDateKey(lastIso), weekStart), 6)
  const weeks: Date[][] = []
  for (let start = gridStart; start <= gridEnd; start = addDays(start, 7)) {
    weeks.push(Array.from({ length: 7 }, (_, index) => addDays(start, index)))
  }
  return weeks
}

export function snapMinutes(minutes: number, step = 15): number {
  return Math.round(minutes / step) * step
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/* ---- Formatting ------------------------------------------------------ */

const formatters = new Map<string, Intl.DateTimeFormat>()

export function formatDate(
  date: Date,
  locale: string,
  options: Intl.DateTimeFormatOptions
): string {
  const cacheKey = `${locale}|${JSON.stringify(options)}`
  let formatter = formatters.get(cacheKey)
  if (!formatter) {
    try {
      formatter = new Intl.DateTimeFormat(locale, options)
    } catch {
      formatter = new Intl.DateTimeFormat(undefined, options)
    }
    formatters.set(cacheKey, formatter)
  }
  return formatter.format(date)
}

export function formatTime(date: Date, locale: string): string {
  return formatDate(date, locale, { hour: 'numeric', minute: '2-digit' })
}

/** Hour labels: "1 PM" where the locale counts twelve hours, "13:00" elsewhere. */
export function formatHour(hour: number, locale: string): string {
  const date = new Date(2000, 0, 1, hour)
  return usesTwelveHours(locale)
    ? formatDate(date, locale, { hour: 'numeric' })
    : formatDate(date, locale, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
}

export function usesTwelveHours(locale: string): boolean {
  try {
    const cycle = new Intl.DateTimeFormat(locale, { hour: 'numeric' }).resolvedOptions().hourCycle
    return cycle === 'h12' || cycle === 'h11'
  } catch {
    return false
  }
}

export function formatMonthTitle(date: Date, locale: string): string {
  return formatDate(date, locale, { year: 'numeric', month: 'long' })
}

export function formatLongDay(date: Date, locale: string): string {
  return formatDate(date, locale, { month: 'long', day: 'numeric', weekday: 'short' })
}

export function formatWeekday(
  date: Date,
  locale: string,
  width: 'short' | 'narrow' = 'short'
): string {
  return formatDate(date, locale, { weekday: width })
}

export function formatShortDate(date: Date, locale: string): string {
  return formatDate(date, locale, { month: 'short', day: 'numeric' })
}
