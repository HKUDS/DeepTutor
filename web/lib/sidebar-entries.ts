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

import type { StudyCourse } from "@/lib/courses-api";
import type { MasteryTopicLabel } from "@/lib/learning-api";
import { masteryPathIdOf, readingWorkspaceIdOf } from "@/lib/mastery-session";
import type { ReadingCollectionLabel } from "@/lib/reading-workspace-api";
import type { SessionSummary } from "@/lib/session-api";
import { applyManualOrder } from "@/lib/sidebar-layout";

/** Which surface a group entry stands for. Decides only its mark. */
export type SidebarGroupKind = "mastery" | "reading" | "course";

export interface SidebarSessionEntry {
  kind: "session";
  /** The session id — also this entry's key in the hand-arranged order. */
  id: string;
  session: SessionSummary;
}

export interface SidebarGroupEntry {
  kind: "group";
  /** Topic, collection or course id — this entry's key in the order. */
  id: string;
  group: SidebarGroupKind;
  label: string;
  /** A course's own colour; topics and collections carry an icon instead. */
  color?: string;
  /** The conversations inside, newest first. */
  rows: SessionSummary[];
}

export type SidebarEntry = SidebarSessionEntry | SidebarGroupEntry;

export interface SidebarEntriesInput {
  /** Root conversations, already in the order they should be listed. */
  roots: readonly SessionSummary[];
  courses?: readonly StudyCourse[];
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
  color?: string;
}

/**
 * The group a conversation belongs in, or null when it stands on its own.
 *
 * A study conversation files under its topic first. It can also carry a course
 * id — a path reached from a course keeps that link — but the topic is the
 * container it was actually held in, so filing it under the course would put it
 * where the learner never looks for it. A reading conversation files under its
 * collection for the same reason: the reader, its material and its citations
 * are that conversation's context.
 *
 * A container whose label is gone (topic deleted, course removed) yields null:
 * the conversation is then listed on its own rather than disappearing with its
 * heading, which is the only outcome that never loses it.
 */
function containerOf(
  session: SessionSummary,
  labels: {
    topics: ReadonlyMap<string, MasteryTopicLabel>;
    collections: ReadonlyMap<string, ReadingCollectionLabel>;
    courses: ReadonlyMap<string, StudyCourse>;
  },
): Container | null {
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
  const courseId = String(session.preferences?.course_id || "");
  if (courseId) {
    const course = labels.courses.get(courseId);
    return course
      ? {
          id: courseId,
          group: "course",
          label: course.name,
          color: course.color,
        }
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
  courses = [],
  masteryTopics = [],
  readingCollections = [],
  manualOrder = [],
}: SidebarEntriesInput): SidebarEntry[] {
  const labels = {
    topics: new Map(masteryTopics.map((topic) => [topic.path_id, topic])),
    collections: new Map(
      readingCollections.map((collection) => [
        collection.workspace_id,
        collection,
      ]),
    ),
    courses: new Map(courses.map((course) => [course.id, course])),
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
