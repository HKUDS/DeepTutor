"use client";

import { useEffect, useState } from "react";

import { subscribeSessionChanges } from "@/lib/session-events";
import {
  listWorkspaces,
  type ChatWorkspaceRegistration,
} from "@/lib/workspaces-api";

let cachedWorkspaces: ChatWorkspaceRegistration[] | null = null;

/**
 * The workspaces a conversation can be filed under.
 *
 * Only the user-created ones: ``system`` is a read-only configuration snapshot
 * and ``general`` is the absence of a binding, so neither is a destination. A
 * workspace is created and renamed from settings, and a conversation is moved
 * from three different surfaces (composer pill, sidebar row menu, chat header),
 * so every surface reloads on the same signal the session list uses instead of
 * each keeping its own idea of what exists.
 *
 * The module-level cache exists so a route-group remount (which happens on
 * every `(workspace)` ↔ `(utility)` crossing) restores the list in its first
 * frame instead of flashing an empty workspace name while `listWorkspaces`
 * runs again.
 */
export function useChatWorkspaces() {
  const [workspaces, setWorkspaces] = useState<ChatWorkspaceRegistration[]>(
    () => cachedWorkspaces ?? [],
  );
  const [loaded, setLoaded] = useState(() => cachedWorkspaces !== null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    const refresh = () =>
      void listWorkspaces(true)
        .then((rows) => {
          const filtered = rows.filter((row) => row.kind === "workspace");
          cachedWorkspaces = filtered;
          if (!alive) return;
          setWorkspaces(filtered);
          setLoaded(true);
          setError("");
        })
        .catch((err) => {
          if (alive) {
            setLoaded(true);
            setError(err instanceof Error ? err.message : String(err));
          }
        });
    refresh();
    const unsubscribe = subscribeSessionChanges(refresh);
    return () => {
      alive = false;
      unsubscribe();
    };
  }, []);

  return { workspaces, loaded, error };
}
