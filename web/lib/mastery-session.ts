/**
 * Which surface a conversation belongs to — the one place that decides.
 *
 * A mastery study conversation is an ordinary chat session that happens to
 * carry `mastery_path_id` in its preferences. Two surfaces need to read that:
 * the sidebar, to file the conversation under its topic, and the click
 * handler, to open it on `/mastery/<path>/sessions/<session>` instead of `/chat`.
 * If those two ever disagreed, a conversation would render under a topic and
 * then navigate somewhere else — so the rule lives here and neither owns it.
 *
 * Workspace mode and path id are both required. The capability is a per-turn
 * action (Chat, Quiz, Research, ...), so it never decides which product
 * surface owns the conversation.
 *
 * Immersive Reading conversations answer the same question with their own
 * pair of signals, and land on their collection instead. They are here rather
 * than in a second module for the reason above: if two places decided where a
 * conversation lives, the sidebar would file one under a heading and then
 * navigate somewhere else.
 */

import type { SessionSummary } from "@/lib/session-api";

export function masteryPathIdOf(session: SessionSummary): string {
  const preferences = session.preferences;
  if (!preferences) return "";
  if (preferences.workspace_mode !== "mastery_path") return "";
  return String(preferences.mastery_path_id || "");
}

/**
 * Which reading collection a conversation belongs to, or "".
 *
 * Both signals again, and for the same reason: `session_kind` says the
 * conversation was held in the reader, `reading_workspace_id` says which
 * collection it was held in. The backend writes both together, on the
 * conversation's first turn and whenever a reading session is attached.
 */
export function readingWorkspaceIdOf(session: SessionSummary): string {
  const preferences = session.preferences;
  if (!preferences) return "";
  if (preferences.workspace_mode !== "immersive_reading") return "";
  return String(preferences.reading_workspace_id || "");
}

/**
 * The reverse of the `/reading/...` branch of `sessionRoute`: which
 * conversation a reading URL names, or null for "a new one".
 *
 * It reads the path rather than route params because the workspace binds the
 * first turn's session id with the native history API — see the binding effect
 * in `useReadingWorkspace` for why — and only `usePathname` follows that.
 * It lives beside the function that writes these URLs because they are one
 * rule in two directions: if they ever disagreed, the first turn would land on
 * a URL the workspace then read as "new" and start the conversation over.
 */
export function readingSessionIdFromPath(pathname: string): string | null {
  const match = /^\/reading\/[^/]+\/sessions\/([^/?#]+)/.exec(pathname);
  if (!match) return null;
  return decodeURIComponent(match[1]).trim() || null;
}

/** Where clicking this conversation should land. */
export function sessionRoute(session: SessionSummary): string {
  const sessionId = encodeURIComponent(session.session_id);
  const pathId = masteryPathIdOf(session);
  if (pathId) {
    return `/mastery/${encodeURIComponent(pathId)}/sessions/${sessionId}`;
  }
  // The reader, its outline and the material are the context this was held
  // in; /chat would drop all three and leave the citations pointing at a
  // document that is not open.
  const workspaceId = readingWorkspaceIdOf(session);
  if (workspaceId) {
    return `/reading/${encodeURIComponent(workspaceId)}/sessions/${sessionId}`;
  }
  return `/chat/${sessionId}`;
}
