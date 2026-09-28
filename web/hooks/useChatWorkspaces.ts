"use client";

import { useEffect, useState } from "react";

import { subscribeSessionChanges } from "@/lib/session-events";
import {
  listWorkspaces,
  type ChatWorkspaceRegistration,
} from "@/lib/workspaces-api";

/**
 * The workspaces a conversation can be filed under.
 *
 * Only the user-created ones: ``system`` is a read-only configuration snapshot
 * and ``general`` is the absence of a binding, so neither is a destination. A
 * workspace is created and renamed from settings, and a conversation is moved
 * from three different surfaces (composer pill, sidebar row menu, chat header),
 * so every surface reloads on the same signal the session list uses instead of
 * each keeping its own idea of what exists.
 */
export function useChatWorkspaces() {
  const [workspaces, setWorkspaces] = useState<ChatWorkspaceRegistration[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    const refresh = () =>
      void listWorkspaces(true)
        .then((rows) => {
          if (!alive) return;
          setWorkspaces(rows.filter((row) => row.kind === "workspace"));
          setError("");
        })
        .catch((err) => {
          if (alive) setError(err instanceof Error ? err.message : String(err));
        });
    refresh();
    const unsubscribe = subscribeSessionChanges(refresh);
    return () => {
      alive = false;
      unsubscribe();
    };
  }, []);

  return { workspaces, error };
}
