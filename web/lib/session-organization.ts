import type { SessionSummary } from "@/lib/session-api";

/** No conversation is streaming — the default for callers without a runtime. */
const NOTHING_LIVE: ReadonlySet<string> = new Set();

/**
 * Pinned first, then whatever the caller is streaming right now, then recency.
 *
 * The streaming lift earns its place because the sidebar list is refetched
 * when a turn *ends*, not when one starts: send a message into a conversation
 * from last week and without the lift the one conversation you are waiting on
 * stays buried where its old timestamp left it.
 *
 * That signal has to come from the caller's live runtime rather than from the
 * session's own persisted ``status``: a turn that dies without writing a
 * terminal status stays "running" in the database indefinitely, and trusting
 * that would nail a long-dead conversation to the top of the sidebar with
 * nothing the learner could do about it.
 */
function compareSessions(
  a: SessionSummary,
  b: SessionSummary,
  live: ReadonlySet<string>,
): number {
  const pinned =
    Number(Boolean(b.preferences?.pinned)) -
    Number(Boolean(a.preferences?.pinned));
  if (pinned) return pinned;
  const streaming =
    Number(live.has(b.session_id)) - Number(live.has(a.session_id));
  return streaming || b.updated_at - a.updated_at;
}

/** Build a render-safe tree even if legacy organization data contains a cycle. */
export function organizeSessionTree(
  sessions: SessionSummary[],
  nested: boolean,
  /** Conversations the caller's runtime is streaming right now, if any. */
  liveSessionIds: ReadonlySet<string> = NOTHING_LIVE,
): {
  roots: SessionSummary[];
  childrenByParent: Map<string, SessionSummary[]>;
} {
  const byId = new Map(
    sessions.map((session) => [session.session_id, session]),
  );
  const childrenByParent = new Map<string, SessionSummary[]>();
  const roots: SessionSummary[] = [];

  for (const session of sessions) {
    const proposedParent = String(session.preferences?.parent_session_id || "");
    let parentId = nested && byId.has(proposedParent) ? proposedParent : "";
    if (parentId) {
      const visited = new Set([session.session_id]);
      let cursor = parentId;
      while (cursor && byId.has(cursor)) {
        if (visited.has(cursor)) {
          parentId = "";
          break;
        }
        visited.add(cursor);
        cursor = String(byId.get(cursor)?.preferences?.parent_session_id || "");
      }
    }

    if (!parentId) {
      roots.push(session);
      continue;
    }
    const children = childrenByParent.get(parentId) ?? [];
    children.push(session);
    childrenByParent.set(parentId, children);
  }

  const byPriority = (a: SessionSummary, b: SessionSummary) =>
    compareSessions(a, b, liveSessionIds);
  roots.sort(byPriority);
  for (const children of childrenByParent.values()) children.sort(byPriority);
  return { roots, childrenByParent };
}
