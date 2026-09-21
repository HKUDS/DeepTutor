import type { components } from '@/contracts/generated/api'
import { apiFetch, apiUrl } from '@/lib/api'

export type UsageStatistics = components['schemas']['UsageStatistics']
export type DailyUsage = components['schemas']['DailyUsage']

export async function fetchUsageStatistics(
  year: number,
  signal?: AbortSignal
): Promise<UsageStatistics> {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const query = new URLSearchParams({ year: String(year), timezone })
  const response = await apiFetch(apiUrl(`/api/settings/usage?${query}`), { signal })
  if (!response.ok) throw new Error(`Usage request failed (${response.status})`)
  return response.json()
}

export function usageYear(value: string | null, current: number): number {
  const year = Number(value)
  return Number.isInteger(year) && year >= 1970 && year <= current ? year : current
}

/** UTC calendar arithmetic avoids DST gaps; the API already bins in local time. */
export function activityCalendar(days: readonly DailyUsage[], year: number) {
  const byDate = new Map(days.map(day => [day.date, day]))
  const start = new Date(Date.UTC(year, 0, 1))
  const offset = (start.getUTCDay() + 6) % 7
  const dates: DailyUsage[] = []
  for (
    let day = new Date(start);
    day.getUTCFullYear() === year;
    day.setUTCDate(day.getUTCDate() + 1)
  ) {
    const date = day.toISOString().slice(0, 10)
    dates.push(
      byDate.get(date) ?? { date, total_tokens: 0, total_calls: 0, turns: 0, tracked_turns: 0 }
    )
  }
  const weeks: (DailyUsage | null)[][] = []
  for (let week = 0; week < Math.ceil((offset + dates.length) / 7); week++) {
    weeks.push(
      Array.from({ length: 7 }, (_, weekday) => dates[week * 7 + weekday - offset] ?? null)
    )
  }
  return { weeks, dates, offset }
}
