"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getSessionOrganization,
  type SessionSummary,
} from "@/lib/session-api";

/** The parts of a conversation its menu reads; both the list row and the
 *  detail a write returns carry them. */
export type SessionOrganization = Pick<
  SessionSummary,
  "session_id" | "title" | "preferences" | "status" | "content_workspace_id"
>;
import { subscribeSessionChanges } from "@/lib/session-events";

/**
 * The open conversation's own organization — pinned, archived, filed under —
 * read without its transcript and refetched whenever a session list changes,
 * so the chat header agrees with a change made from the sidebar (and the
 * sidebar, which listens to the same event, with one made from the header).
 */
export function useSessionOrganization(
  sessionId: string | null,
  workspaceId: string,
): {
  row: SessionOrganization | null;
  apply: (row: SessionOrganization) => void;
} {
  const [state, setState] = useState<{
    id: string;
    row: SessionOrganization;
  } | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(
    () => subscribeSessionChanges(() => setRevision((value) => value + 1)),
    [],
  );

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    getSessionOrganization(sessionId, workspaceId, controller.signal)
      .then((row) => setState({ id: sessionId, row }))
      .catch(() => {
        /* a deleted or unreadable conversation keeps the last known state */
      });
    return () => controller.abort();
  }, [revision, sessionId, workspaceId]);

  const apply = useCallback(
    (row: SessionOrganization) => {
      if (sessionId) setState({ id: sessionId, row });
    },
    [sessionId],
  );

  return { row: state?.id === sessionId ? state.row : null, apply };
}
