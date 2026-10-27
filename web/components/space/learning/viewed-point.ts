import type { MasteryMode } from "@/lib/mastery-mode";

export interface ViewedPoint {
  id: string;
  name: string;
}

/**
 * The knowledge point whose conversation is open.
 *
 * A study or review session is placed on one point. Until that placement is
 * known, the path's next step must not stand in for it: next can be a
 * different point, and the outline would light the wrong row while the
 * session is still opening. An outline session is not on a point. A study
 * session that has loaded and still has no placement is an older unplaced
 * conversation, and next is the only cursor it has.
 */
export function viewedKnowledgePoint(
  modules: readonly { knowledge_points: readonly ViewedPoint[] }[],
  boundPointId: string | null,
  sessionMode: MasteryMode,
  nextPoint: ViewedPoint,
): ViewedPoint | null {
  if (boundPointId === null) return null;
  const placed = boundPointId.trim();
  if (placed) {
    for (const region of modules) {
      const point = region.knowledge_points.find((item) => item.id === placed);
      if (point) return { id: point.id, name: point.name };
    }
    return null;
  }
  if (sessionMode === "outline") return null;
  return nextPoint.id ? nextPoint : null;
}
