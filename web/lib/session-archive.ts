/**
 * What the archive holds, sorted into the three surfaces it came from.
 *
 * Archiving a conversation only clears it out of the sidebar — nothing is
 * deleted and the flag is one boolean in the session's preferences. Until now
 * the only place that read the flag back was the chat-history console's filter
 * and a course page's own archive block, so an archived study or reading
 * conversation had no surface at all: it left the sidebar and, unless you knew
 * the console existed, that was the last you saw of it.
 *
 * Pure and free of React so the bucketing and the parent rule below can be
 * tested on their own.
 */

import type { MasteryTopicLabel } from "@/lib/learning-api";
import { masteryPathIdOf, readingWorkspaceIdOf } from "@/lib/mastery-session";
import type { ReadingCollectionLabel } from "@/lib/reading-workspace-api";
import type { SessionSummary } from "@/lib/session-api";

/** Which surface an archived conversation was held in. */
export type ArchiveKind = "chat" | "mastery" | "reading";

export interface ArchivedConversation {
  session: SessionSummary;
  kind: ArchiveKind;
  /**
   * The topic or collection it belongs to, named. Empty for a plain
   * conversation, and also for one whose topic or collection no longer
   * exists — the conversation is still listed either way.
   */
  container: string;
}

export interface ArchiveBuckets {
  chat: ArchivedConversation[];
  mastery: ArchivedConversation[];
  reading: ArchivedConversation[];
}

export interface ArchiveInput {
  sessions: readonly SessionSummary[];
  masteryTopics?: readonly MasteryTopicLabel[];
  readingCollections?: readonly ReadingCollectionLabel[];
}

/** Newest first, the same order every other conversation list uses. */
function byRecency(a: ArchivedConversation, b: ArchivedConversation): number {
  return b.session.updated_at - a.session.updated_at;
}

/**
 * Split the archived conversations out of a full session list.
 *
 * A selected-text tutor thread is left out whenever the conversation it hangs
 * off is archived too: the backend archives and restores those together with
 * their parent, so listing them separately would offer a restore button that
 * silently does nothing on its own. A thread whose parent is *not* archived
 * was archived by hand and is listed like anything else.
 */
export function collectArchivedConversations({
  sessions,
  masteryTopics = [],
  readingCollections = [],
}: ArchiveInput): ArchiveBuckets {
  const topics = new Map(masteryTopics.map((topic) => [topic.path_id, topic]));
  const collections = new Map(
    readingCollections.map((collection) => [
      collection.workspace_id,
      collection,
    ]),
  );
  const archivedIds = new Set(
    sessions
      .filter((session) => session.preferences?.archived)
      .map((session) => session.session_id),
  );

  const buckets: ArchiveBuckets = { chat: [], mastery: [], reading: [] };
  for (const session of sessions) {
    if (!session.preferences?.archived) continue;
    const parentId = String(session.preferences?.parent_session_id || "");
    if (parentId && archivedIds.has(parentId)) continue;

    const topicId = masteryPathIdOf(session);
    if (topicId) {
      buckets.mastery.push({
        session,
        kind: "mastery",
        container: topics.get(topicId)?.name ?? "",
      });
      continue;
    }
    const collectionId = readingWorkspaceIdOf(session);
    if (collectionId) {
      buckets.reading.push({
        session,
        kind: "reading",
        container: collections.get(collectionId)?.title ?? "",
      });
      continue;
    }
    buckets.chat.push({ session, kind: "chat", container: "" });
  }

  buckets.chat.sort(byRecency);
  buckets.mastery.sort(byRecency);
  buckets.reading.sort(byRecency);
  return buckets;
}

/** How many conversations the archive holds in total. */
export function archiveCount(buckets: ArchiveBuckets): number {
  return buckets.chat.length + buckets.mastery.length + buckets.reading.length;
}
