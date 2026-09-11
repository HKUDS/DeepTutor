import { codeRanges } from "@/lib/reading-citations";

export const MEDIA_TIME_HREF_PREFIX = "#dt-media-time-";
const TIMESTAMP = /\[(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)\]/g;

/** Turn bare [MM:SS] / [H:MM:SS] evidence markers into seek links. */
export function linkifyMediaTimestamps(text: string): string {
  const skip = codeRanges(text);
  return text.replace(
    TIMESTAMP,
    (
      raw,
      hours: string | undefined,
      minutes: string,
      seconds: string,
      offset: number,
    ) => {
      if (skip.some(([from, to]) => offset >= from && offset < to)) return raw;
      if (text[offset + raw.length] === "(") return raw;
      const total =
        Number(hours || 0) * 3600 + Number(minutes) * 60 + Number(seconds);
      return `${raw}(${MEDIA_TIME_HREF_PREFIX}${total})`;
    },
  );
}

export function mediaTimeFromHref(
  href: string | null | undefined,
): number | null {
  if (!href?.startsWith(MEDIA_TIME_HREF_PREFIX)) return null;
  const value = Number(href.slice(MEDIA_TIME_HREF_PREFIX.length));
  return Number.isFinite(value) && value >= 0 ? value : null;
}
