import { addDays, dateKey, formatDate, fromDateKey, type DateKey } from './dates'

/**
 * The repeat rules the editor offers, as RFC 5545 RRULE values (no
 * `RRULE:` prefix, no DTSTART: the event's start anchors the series).
 * Parts the editor does not model are carried through untouched, so an
 * imported rule survives an unrelated edit.
 */

export type Frequency = 'DAILY' | 'WEEKLY' | 'MONTHLY' | 'YEARLY'
export type RepeatEnd =
  { kind: 'never' } | { kind: 'until'; date: DateKey } | { kind: 'count'; count: number }

/** Indexed like `Date.getDay()`: Sunday first. */
export const WEEKDAY_CODES = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'] as const

export interface RecurrenceRule {
  freq: Frequency
  interval: number
  /** Weekly: the days it falls on. */
  byDay: number[]
  /** Monthly by weekday: `{ ordinal: 3, weekday: 4 }` is the third Thursday; -1 is the last. */
  monthlyWeekday: { ordinal: number; weekday: number } | null
  end: RepeatEnd
  /** Parts kept verbatim (BYHOUR, WKST, …). */
  extra: string[]
}

export type RepeatPreset =
  'none' | 'daily' | 'weekdays' | 'weekly' | 'monthly' | 'monthlyWeekday' | 'yearly' | 'custom'

const WORKWEEK = [1, 2, 3, 4, 5]

function untilToDateKey(value: string): DateKey | null {
  const match = /^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z)?)?$/.exec(value)
  if (!match) return null
  const [, y, m, d, hh, mm, ss, utc] = match
  if (!hh) return `${y}-${m}-${d}`
  const instant = utc
    ? new Date(Date.UTC(+y, +m - 1, +d, +hh, +mm, +ss))
    : new Date(+y, +m - 1, +d, +hh, +mm, +ss)
  return dateKey(instant)
}

export function parseRule(text: string | null | undefined): RecurrenceRule | null {
  if (!text) return null
  const rule: RecurrenceRule = {
    freq: 'DAILY',
    interval: 1,
    byDay: [],
    monthlyWeekday: null,
    end: { kind: 'never' },
    extra: [],
  }
  let hasFreq = false
  for (const part of text.replace(/^RRULE:/i, '').split(';')) {
    const [rawName, value = ''] = part.split('=')
    const name = rawName.trim().toUpperCase()
    if (!name) continue
    if (name === 'FREQ' && ['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'].includes(value)) {
      rule.freq = value as Frequency
      hasFreq = true
    } else if (name === 'INTERVAL' && Number(value) >= 1) rule.interval = Math.floor(Number(value))
    else if (name === 'COUNT' && Number(value) >= 1)
      rule.end = { kind: 'count', count: Math.floor(Number(value)) }
    else if (name === 'UNTIL' && untilToDateKey(value))
      rule.end = { kind: 'until', date: untilToDateKey(value)! }
    else if (name === 'BYDAY') {
      const days = value.split(',')
      const ordinal = /^([+-]?\d)([A-Z]{2})$/.exec(days[0] ?? '')
      if (days.length === 1 && ordinal) {
        const weekday = WEEKDAY_CODES.indexOf(ordinal[2] as (typeof WEEKDAY_CODES)[number])
        if (weekday >= 0) rule.monthlyWeekday = { ordinal: Number(ordinal[1]), weekday }
        else rule.extra.push(part)
      } else {
        const indexes = days.map(day =>
          WEEKDAY_CODES.indexOf(day as (typeof WEEKDAY_CODES)[number])
        )
        if (indexes.every(index => index >= 0))
          rule.byDay = [...new Set(indexes)].sort((a, b) => a - b)
        else rule.extra.push(part)
      }
    } else rule.extra.push(part)
  }
  return hasFreq ? rule : null
}

function formatUntil(date: DateKey, allDay: boolean): string {
  if (allDay) return date.replaceAll('-', '')
  // The last instant of that local day, written in UTC as RFC 5545 requires.
  const end = new Date(fromDateKey(addDaysKey(date, 1)).getTime() - 1000)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${end.getUTCFullYear()}${pad(end.getUTCMonth() + 1)}${pad(end.getUTCDate())}T${pad(end.getUTCHours())}${pad(end.getUTCMinutes())}${pad(end.getUTCSeconds())}Z`
}

function addDaysKey(key: DateKey, days: number): DateKey {
  return dateKey(addDays(fromDateKey(key), days))
}

export function buildRule(rule: RecurrenceRule, allDay: boolean): string {
  const parts = [`FREQ=${rule.freq}`]
  if (rule.interval > 1) parts.push(`INTERVAL=${rule.interval}`)
  if (rule.freq === 'WEEKLY' && rule.byDay.length)
    parts.push(`BYDAY=${rule.byDay.map(day => WEEKDAY_CODES[day]).join(',')}`)
  if (rule.freq === 'MONTHLY' && rule.monthlyWeekday)
    parts.push(`BYDAY=${rule.monthlyWeekday.ordinal}${WEEKDAY_CODES[rule.monthlyWeekday.weekday]}`)
  if (rule.end.kind === 'count') parts.push(`COUNT=${rule.end.count}`)
  if (rule.end.kind === 'until') parts.push(`UNTIL=${formatUntil(rule.end.date, allDay)}`)
  parts.push(...rule.extra.filter(part => !/^(FREQ|INTERVAL|BYDAY|COUNT|UNTIL)=/i.test(part)))
  return parts.join(';')
}

/** Which of its weekday's dates in the month this is: 1–4, or -1 for a fifth (the last). */
export function weekdayOrdinal(date: Date): number {
  const nth = Math.floor((date.getDate() - 1) / 7) + 1
  return nth === 5 ? -1 : nth
}

export function defaultRule(freq: Frequency, start: Date): RecurrenceRule {
  return {
    freq,
    interval: 1,
    byDay: freq === 'WEEKLY' ? [start.getDay()] : [],
    monthlyWeekday: null,
    end: { kind: 'never' },
    extra: [],
  }
}

export function presetRule(preset: RepeatPreset, start: Date, allDay: boolean): string | null {
  switch (preset) {
    case 'none':
    case 'custom':
      return null
    case 'daily':
      return buildRule(defaultRule('DAILY', start), allDay)
    case 'weekdays':
      return buildRule({ ...defaultRule('WEEKLY', start), byDay: WORKWEEK }, allDay)
    case 'weekly':
      return buildRule(defaultRule('WEEKLY', start), allDay)
    case 'monthly':
      return buildRule(defaultRule('MONTHLY', start), allDay)
    case 'monthlyWeekday':
      return buildRule(
        {
          ...defaultRule('MONTHLY', start),
          monthlyWeekday: { ordinal: weekdayOrdinal(start), weekday: start.getDay() },
        },
        allDay
      )
    case 'yearly':
      return buildRule(defaultRule('YEARLY', start), allDay)
  }
}

/** The preset a stored rule matches, or `custom` for anything else. */
export function detectPreset(text: string | null | undefined, start: Date): RepeatPreset {
  const rule = parseRule(text)
  if (!rule) return 'none'
  if (rule.interval !== 1 || rule.end.kind !== 'never' || rule.extra.length) return 'custom'
  if (rule.freq === 'DAILY') return 'daily'
  if (rule.freq === 'WEEKLY') {
    if (rule.byDay.join() === WORKWEEK.join()) return 'weekdays'
    if (!rule.byDay.length || (rule.byDay.length === 1 && rule.byDay[0] === start.getDay()))
      return 'weekly'
    return 'custom'
  }
  if (rule.freq === 'MONTHLY')
    return rule.monthlyWeekday
      ? rule.monthlyWeekday.weekday === start.getDay() &&
        rule.monthlyWeekday.ordinal === weekdayOrdinal(start)
        ? 'monthlyWeekday'
        : 'custom'
      : 'monthly'
  return 'yearly'
}

type Translate = (key: string, options?: Record<string, unknown>) => string

function weekdayName(day: number, locale: string, width: 'long' | 'short'): string {
  // 2023-01-01 was a Sunday.
  return formatDate(new Date(2023, 0, 1 + day), locale, { weekday: width })
}

function listOf(items: string[], locale: string): string {
  try {
    return new Intl.ListFormat(locale, { style: 'narrow', type: 'conjunction' }).format(items)
  } catch {
    return items.join(', ')
  }
}

const ORDINAL_KEYS: Record<number, string> = {
  1: 'Monthly on the first {{weekday}}',
  2: 'Monthly on the second {{weekday}}',
  3: 'Monthly on the third {{weekday}}',
  4: 'Monthly on the fourth {{weekday}}',
  [-1]: 'Monthly on the last {{weekday}}',
}

/** A sentence for a rule, e.g. "Weekly on Mon and Wed, until Dec 31". */
export function describeRule(
  text: string | null | undefined,
  start: Date,
  locale: string,
  t: Translate
): string {
  const rule = parseRule(text)
  if (!rule) return t('Does not repeat')
  const count = rule.interval
  let base: string
  switch (rule.freq) {
    case 'DAILY':
      base = count > 1 ? t('Every {{count}} days', { count }) : t('Every day')
      break
    case 'WEEKLY': {
      const days = rule.byDay.length ? rule.byDay : [start.getDay()]
      if (count === 1 && days.join() === WORKWEEK.join())
        base = t('Every weekday (Monday to Friday)')
      else {
        const names = listOf(
          days.map(day => weekdayName(day, locale, days.length > 2 ? 'short' : 'long')),
          locale
        )
        base =
          count > 1
            ? t('Every {{count}} weeks on {{days}}', { count, days: names })
            : t('Weekly on {{days}}', { days: names })
      }
      break
    }
    case 'MONTHLY':
      if (rule.monthlyWeekday) {
        base = t(ORDINAL_KEYS[rule.monthlyWeekday.ordinal] ?? ORDINAL_KEYS[1], {
          weekday: weekdayName(rule.monthlyWeekday.weekday, locale, 'long'),
        })
        if (count > 1) base = `${base} · ${t('every {{count}} months', { count })}`
      } else
        base =
          count > 1
            ? t('Every {{count}} months on day {{day}}', { count, day: start.getDate() })
            : t('Monthly on day {{day}}', { day: start.getDate() })
      break
    case 'YEARLY': {
      const date = formatDate(start, locale, { month: 'long', day: 'numeric' })
      base =
        count > 1
          ? t('Every {{count}} years on {{date}}', { count, date })
          : t('Annually on {{date}}', { date })
      break
    }
  }
  if (rule.end.kind === 'until')
    return t('{{rule}}, until {{date}}', {
      rule: base,
      date: formatDate(fromDateKey(rule.end.date), locale, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      }),
    })
  if (rule.end.kind === 'count')
    return t('{{rule}}, {{count}} times', { rule: base, count: rule.end.count })
  return base
}
