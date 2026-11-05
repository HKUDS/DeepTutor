/**
 * What the sidebar's history region lists, and in what order.
 *
 * The region used to be three stacked tables — a "Chat" heading over the home
 * conversations, then one heading per mastery topic, then one per reading
 * collection — so a conversation held ten minutes ago sat below headings whose
 * newest conversation was a week old, and the surface you were last working in
 * was never the thing at the top.
 *
 * Here there is one list instead. A home conversation is an entry; a topic or a
 * collection is *also* an entry — a single collapsible unit sitting at the same
 * level as a conversation, ranked by the newest conversation inside it. So the
 * list reads by recency all the way down whatever surface the work happened on,
 * and one hand-arranged order (see ``applyManualOrder``) covers both kinds.
 *
 * Pure and free of React so the ordering can be tested on its own.
 */

import type { MasteryTopicLabel } from "@/lib/learning-api";
import { masteryPathIdOf, readingWorkspaceIdOf } from "@/lib/mastery-session";
import type { ReadingCollectionLabel } from "@/lib/reading-workspace-api";
import type { SessionSummary } from "@/lib/session-api";
import { applyManualOrder } from "@/lib/sidebar-layout";

/** Which surface a group entry stands for. Decides only its mark. */
export type SidebarGroupKind = "mastery" | "reading" | "recent";

export interface SidebarSessionEntry {
  kind: "session";
  /** The session id — also this entry's key in the hand-arranged order. */
  id: string;
  session: SessionSummary;
}

export interface SidebarGroupEntry {
  kind: "group";
  /** Topic or collection id — this entry's key in the order. */
  id: string;
  group: SidebarGroupKind;
  label: string;
  /** The conversations inside, newest first. */
  rows: SessionSummary[];
}

export type SidebarEntry = SidebarSessionEntry | SidebarGroupEntry;

export interface SidebarEntriesInput {
  /** Root conversations, already in the order they should be listed. */
  roots: readonly SessionSummary[];
  /** File every conversation under one "Recent" heading instead of its own groups. */
  recents?: boolean;
  /** Topics whose study conversations get their own entry. Omit for none. */
  masteryTopics?: readonly MasteryTopicLabel[];
  /** Collections whose reading conversations get their own entry. */
  readingCollections?: readonly ReadingCollectionLabel[];
  /** Hand-arranged order over the entries, by entry id. */
  manualOrder?: readonly string[];
}

interface Container {
  id: string;
  group: SidebarGroupKind;
  label: string;
}

/**
 * The group a conversation belongs in, or null when it stands on its own.
 *
 * Study conversations file under their topic, and reading conversations under
 * their collection. If its label is gone, a conversation is listed on its own.
 */
function containerOf(
  session: SessionSummary,
  labels: {
    topics: ReadonlyMap<string, MasteryTopicLabel>;
    collections: ReadonlyMap<string, ReadingCollectionLabel>;
    recents: boolean;
  },
): Container | null {
  if (labels.recents) {
    return { id: "recent:unassigned", group: "recent", label: "Recent" };
  }
  const topicId = masteryPathIdOf(session);
  if (topicId) {
    const topic = labels.topics.get(topicId);
    return topic ? { id: topicId, group: "mastery", label: topic.name } : null;
  }
  const collectionId = readingWorkspaceIdOf(session);
  if (collectionId) {
    const collection = labels.collections.get(collectionId);
    return collection
      ? { id: collectionId, group: "reading", label: collection.title }
      : null;
  }
  return null;
}

/**
 * One flat, recency-ordered list of conversations and groups.
 *
 * A group takes the slot of the newest conversation in it, so an active topic
 * outranks a stale chat and a stale topic sinks below today's conversation —
 * which is the whole point of putting the two at the same level. Within a
 * group the rows keep the order they arrived in.
 */
export function buildSidebarEntries({
  roots,
  recents = false,
  masteryTopics = [],
  readingCollections = [],
  manualOrder = [],
}: SidebarEntriesInput): SidebarEntry[] {
  const labels = {
    recents,
    topics: new Map(masteryTopics.map((topic) => [topic.path_id, topic])),
    collections: new Map(
      readingCollections.map((collection) => [
        collection.workspace_id,
        collection,
      ]),
    ),
  };

  const entries: SidebarEntry[] = [];
  const openGroups = new Map<string, SidebarGroupEntry>();
  for (const session of roots) {
    const container = containerOf(session, labels);
    if (!container) {
      entries.push({ kind: "session", id: session.session_id, session });
      continue;
    }
    const open = openGroups.get(container.id);
    if (open) {
      open.rows.push(session);
      continue;
    }
    const entry: SidebarGroupEntry = {
      kind: "group",
      ...container,
      rows: [session],
    };
    openGroups.set(container.id, entry);
    entries.push(entry);
  }

  return applyManualOrder(entries, (entry) => entry.id, manualOrder);
}
