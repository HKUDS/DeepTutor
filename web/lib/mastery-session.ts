import { scopedUrl } from "@/lib/workspace-scope";
import { sessionWorkspaceId } from "@/lib/session-api";
import { bookRoute, masterySessionRoute, readingSessionRoute, watchingRoute } from "@/lib/learning-routes";
/**
 * Which surface a conversation belongs to — the one place that decides.
 *
 * A mastery study conversation is an ordinary chat session that happens to
 * carry `mastery_path_id` in its preferences. Two surfaces need to read that:
 * the sidebar, to file the conversation under its topic, and the click
 * handler, to open it on its topic session route instead of `/chat`.
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
 * The book page a conversation was held on, or null.
 *
 * A page's tutor chat names its book and page in its preferences, written
 * together with the book's own page → conversation record.
 */
export function bookPageOf(session: SessionSummary): { bookId: string; pageId: string } | null {
  const bookId = String(session.preferences?.book_id || "");
  return bookId ? { bookId, pageId: String(session.preferences?.book_page_id || "") } : null;
}

/**
 * The note page a conversation was held beside, or "".
 *
 * The notebook companion's conversations name their page in preferences, the
 * same way a book page's tutor chat does.
 */
export function notePageIdOf(session: SessionSummary): string {
  return String(session.preferences?.note_document_id || "");
}

/**
 * A conversation that belongs to a note page rather than to the history.
 *
 * Page conversations are opened on a line, folded back onto it and listed with
 * the page, so the sidebar's history and the palette leave them out.
 */
export function isNoteSession(session: SessionSummary): boolean {
  return Boolean(notePageIdOf(session));
}

/** Where clicking this conversation should land. */
export function sessionRoute(session: SessionSummary): string {
  return scopedUrl(surfaceRoute(session), sessionWorkspaceId(session));
}

function surfaceRoute(session: SessionSummary): string {
  const sessionId = encodeURIComponent(session.session_id);
  const pathId = masteryPathIdOf(session);
  if (pathId) {
    return masterySessionRoute(pathId, session.session_id, sessionWorkspaceId(session));
  }
  // The reader, its outline and the material are the context this was held
  // in; /chat would drop all three and leave the citations pointing at a
  // document that is not open.
  const workspaceId = readingWorkspaceIdOf(session);
  if (workspaceId) {
    return readingSessionRoute(workspaceId, session.session_id, sessionWorkspaceId(session));
  }
  // Back on its page, beside the text it was about.
  const book = bookPageOf(session);
  if (book) {
    const page = bookRoute(book.bookId, book.pageId || null, sessionWorkspaceId(session));
    return `${page}${page.includes("?") ? "&" : "?"}chat=${sessionId}`;
  }
  // Beside the page it was about, with its companion open on this thread.
  const notePageId = notePageIdOf(session);
  if (notePageId) {
    return `/co-writer/${encodeURIComponent(notePageId)}?chat=${sessionId}`;
  }
  if (
    session.preferences?.workspace_mode === "immersive_watching" ||
    session.preferences?.capability === "immersive_watching"
  ) {
    return watchingRoute(session.session_id, sessionWorkspaceId(session));
  }
  return `/chat/${sessionId}`;
}
