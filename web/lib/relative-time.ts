/**
 * Shared locale-aware time helpers for sidebar / session lists.
 *
 * Two pieces:
 *
 * 1. `getDayGroupKey(ts)` — returns a stable token (`today` / `yesterday` /
 *    `last_7_days` / `earlier`) for grouping. Callers map that token to a
 *    translated label via i18next so the same grouping logic works across
 *    locales.
 *
 * 2. `formatRelativeTime(ts, locale)` — wraps `Intl.RelativeTimeFormat` with
 *    the caller's active locale instead of the previously-hardcoded `"en"`.
 *    Falls back to `"en"` on unsupported locales to match Intl's own
 *    behaviour rather than throwing.
 */

export type DayGroupKey = "today" | "yesterday" | "last_7_days" | "earlier";

export function getDayGroupKey(timestamp: number): DayGroupKey {
  const now = new Date();
  const date = new Date(timestamp * 1000);
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime();
  const startOfItemDay = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  ).getTime();
  const diffDays = Math.floor((startOfToday - startOfItemDay) / 86400000);
  if (diffDays <= 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return "last_7_days";
  return "earlier";
}

export function formatRelativeTime(timestamp: number, locale: string): string {
  const diffSeconds = Math.round(timestamp - Date.now() / 1000);
  const formatter = new Intl.RelativeTimeFormat(locale || "en", {
    numeric: "auto",
  });
  const abs = Math.abs(diffSeconds);
  if (abs < 60) return formatter.format(diffSeconds, "second");
  if (abs < 3600)
    return formatter.format(Math.round(diffSeconds / 60), "minute");
  if (abs < 86400)
    return formatter.format(Math.round(diffSeconds / 3600), "hour");
  return formatter.format(Math.round(diffSeconds / 86400), "day");
}
