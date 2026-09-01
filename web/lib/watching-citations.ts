import { codeRanges } from "@/lib/reading-citations";

export const VIDEO_TIME_HREF_PREFIX = "#dt-video-time-";
const TIMESTAMP = /\[(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)\]/g;

export function linkifyVideoTimestamps(text: string): string {
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
      return `${raw}(${VIDEO_TIME_HREF_PREFIX}${total})`;
    },
  );
}

export function videoTimeFromHref(
  href: string | null | undefined,
): number | null {
  if (!href?.startsWith(VIDEO_TIME_HREF_PREFIX)) return null;
  const value = Number(href.slice(VIDEO_TIME_HREF_PREFIX.length));
  return Number.isFinite(value) && value >= 0 ? value : null;
}
