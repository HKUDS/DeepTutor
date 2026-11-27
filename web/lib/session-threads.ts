/**
 * Little Tutor threads filed under the message they were opened from.
 *
 * A thread records its source message in ``preferences.tutor_source_message_id``
 * (the wire field is ``quoted_message_id``). Threads without one — bare side
 * chats, and threads created before the field existed — have no message-level
 * entry point; they stay reachable from the viewer and Space history.
 *
 * Keys are strings so SQLite rowids and PocketBase record ids group alike.
 */

import type { SessionSummary } from "@/lib/session-api";

export function groupThreadsByMessage(
  threads: readonly SessionSummary[],
): Map<string, SessionSummary[]> {
  const grouped = new Map<string, SessionSummary[]>();
  for (const thread of threads) {
    const preferences = thread.preferences;
    if (preferences?.archived) continue;
    const source = preferences?.tutor_source_message_id;
    if (source == null || source === "") continue;
    const key = String(source);
    const rows = grouped.get(key);
    if (rows) rows.push(thread);
    else grouped.set(key, [thread]);
  }
  return grouped;
}
