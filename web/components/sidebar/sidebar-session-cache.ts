import type { SessionSummary } from "@/lib/session-api";
import type { MasteryTopicLabel } from "@/lib/learning-api";
import type { ReadingCollectionLabel } from "@/lib/reading-workspace-api";

/**
 * The last session snapshot a sidebar loaded, keyed by workspace.
 *
 * `(workspace)` and `(utility)` are separate route groups: crossing between
 * them (chat ↔ co-writer, chat ↔ /space) unmounts whichever sidebar is
 * showing and mounts the other. Both start from `useState([])`, so without a
 * shared snapshot the list visibly empties and refetches on every crossing.
 * A mount reads this cache for its first frame and refreshes silently behind
 * it.
 */
export interface SidebarSessionSnapshot {
  sessions: SessionSummary[];
  masteryTopics: MasteryTopicLabel[];
  readingCollections: ReadingCollectionLabel[];
}

const cache = new Map<string, SidebarSessionSnapshot>();

export function readSidebarSessionCache(
  workspaceId: string,
): SidebarSessionSnapshot | null {
  return cache.get(workspaceId) ?? null;
}

export function writeSidebarSessionCache(
  workspaceId: string,
  snapshot: SidebarSessionSnapshot,
): void {
  cache.set(workspaceId, snapshot);
}

export function updateCachedSessions(
  workspaceId: string,
  updater: (prev: SessionSummary[]) => SessionSummary[],
): void {
  const current = cache.get(workspaceId);
  if (!current) return;
  cache.set(workspaceId, {
    ...current,
    sessions: updater(current.sessions),
  });
}
