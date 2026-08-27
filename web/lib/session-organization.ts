import type { SessionSummary } from "@/lib/session-api";

function byPriority(a: SessionSummary, b: SessionSummary): number {
  const pinned =
    Number(Boolean(b.preferences?.pinned)) -
    Number(Boolean(a.preferences?.pinned));
  return pinned || b.updated_at - a.updated_at;
}

/** Build a render-safe tree even if legacy organization data contains a cycle. */
export function organizeSessionTree(
  sessions: SessionSummary[],
  nested: boolean,
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

  roots.sort(byPriority);
  for (const children of childrenByParent.values()) children.sort(byPriority);
  return { roots, childrenByParent };
}
