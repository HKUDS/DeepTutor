"use client";

import { useReadingTimeHeartbeat } from "./use-reading-time";

export function ReadingTimeHeartbeat(props: Parameters<typeof useReadingTimeHeartbeat>[0]) {
  useReadingTimeHeartbeat(props);
  return null;
}
