/**
 * Which surface a conversation belongs to — the one place that decides.
 *
 * A mastery study conversation is an ordinary chat session that happens to
 * carry `mastery_path_id` in its preferences. Two surfaces need to read that:
 * the sidebar, to file the conversation under its topic, and the click
 * handler, to open it on `/mastery/<path>/study/<session>` instead of `/home`.
 * If those two ever disagreed, a conversation would render under a topic and
 * then navigate somewhere else — so the rule lives here and neither owns it.
 *
 * Workspace mode and path id are both required. The capability is now a
 * per-turn action (Chat, Quiz, Research, ...), so it must not decide which
 * product surface owns the conversation. Legacy sessions that predate
 * `workspace_mode` still fall back to their old capability value.
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
  if (
    preferences.workspace_mode !== "mastery_path" &&
    preferences.capability !== "mastery_path"
  )
    return "";
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
  if (
    preferences.workspace_mode !== "immersive_reading" &&
    preferences.session_kind !== "immersive_reading"
  )
    return "";
  return String(preferences.reading_workspace_id || "");
}

/** Where clicking this conversation should land. */
export function sessionRoute(session: SessionSummary): string {
  const sessionId = encodeURIComponent(session.session_id);
  const pathId = masteryPathIdOf(session);
  if (pathId) {
    return `/mastery/${encodeURIComponent(pathId)}/study/${sessionId}`;
  }
  // The reader, its outline and the material are the context this was held
  // in; /home would drop all three and leave the citations pointing at a
  // document that is not open.
  const workspaceId = readingWorkspaceIdOf(session);
  if (workspaceId) {
    return `/reading/${encodeURIComponent(workspaceId)}/${sessionId}`;
  }
  return `/home/${sessionId}`;
}
