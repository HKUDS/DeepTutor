"use client";

import { useEffect, useState } from "react";

import { fetchPointLecture, type PointLecture } from "@/lib/learning-api";

/**
 * A draft is written just after the turn's message is persisted, which can be
 * a beat behind the stream closing. Look a few more times rather than deciding
 * "there is no lecture" while one is on its way.
 */
const LATE_LECTURE_RETRIES = [1500, 3000, 5000];

/**
 * The lecture for one knowledge point, or ``null`` while it is still unknown.
 *
 * The mode switch needs this to keep review hidden until there is a lecture to
 * read, and the same "lands a beat after the stream" race applies there as to
 * the study draft card. Keyed by point so a stale result never stands in for
 * the point on screen.
 */
export function usePointLectureReady(
  pathId: string,
  knowledgePointId: string,
  refreshToken = 0,
): PointLecture | null {
  const [loaded, setLoaded] = useState<{ pointId: string; lecture: PointLecture } | null>(null);

  useEffect(() => {
    if (!pathId || !knowledgePointId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    const read = async () => {
      try {
        const result = await fetchPointLecture(pathId, knowledgePointId);
        if (cancelled) return;
        setLoaded({ pointId: knowledgePointId, lecture: result });
        if (result.status === "none" && attempt < LATE_LECTURE_RETRIES.length) {
          timer = setTimeout(() => void read(), LATE_LECTURE_RETRIES[attempt++]);
        }
      } catch {
        if (!cancelled) setLoaded(null);
      }
    };
    void read();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [knowledgePointId, pathId, refreshToken]);

  return loaded?.pointId === knowledgePointId ? loaded.lecture : null;
}
