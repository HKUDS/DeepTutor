"use client";

import { useEffect, useState } from "react";

import {
  getWorkspaceResources,
  type ChatWorkspaceRegistration,
  type WorkspaceResourceOption,
} from "@/lib/workspaces-api";

export interface ComposerResourceCatalog {
  skills: WorkspaceResourceOption[];
  mcp: WorkspaceResourceOption[];
}

const EMPTY: ComposerResourceCatalog = { skills: [], mcp: [] };

/**
 * The skills and MCP servers this conversation may narrow itself to.
 *
 * The catalog endpoint answers "what can this account see", already scoped per
 * workspace for skills but not for MCP, so the workspace's own allowlist is
 * applied here as well. That matters beyond tidiness: the backend intersects a
 * turn's selection with the same allowlist, so anything offered here that the
 * workspace excludes would be a picker the user can tick to no effect.
 *
 * A missing allowlist (``null``) is "everything", which is what an unbound
 * conversation and a workspace that never narrowed anything both have.
 */
export function useComposerResources(
  workspaceId: string | null,
  workspaces: ChatWorkspaceRegistration[],
): ComposerResourceCatalog {
  const [catalog, setCatalog] = useState<ComposerResourceCatalog>(EMPTY);
  const allowedMcp =
    (workspaceId
      ? workspaces.find((row) => row.workspace_id === workspaceId)?.resources
          ?.mcp
      : null) ?? null;
  // Depend on the contents rather than the array identity: `workspaces` is
  // refetched on every session change, and re-running on a new array of the
  // same rows would refetch the catalog with it.
  const allowedKey = allowedMcp ? allowedMcp.join("\u0000") : "";

  useEffect(() => {
    let alive = true;
    void getWorkspaceResources(workspaceId ?? "")
      .then((remote) => {
        if (!alive) return;
        const allowed = allowedKey ? new Set(allowedKey.split("\u0000")) : null;
        setCatalog({
          skills: remote.skills ?? [],
          mcp: (remote.mcp ?? []).filter(
            (option) => allowed === null || allowed.has(option.id),
          ),
        });
      })
      .catch(() => {
        // The pickers simply report nothing to pick; a conversation with no
        // selection inherits its workspace, so this degrades to the old
        // behaviour rather than to an error the user must dismiss.
        if (alive) setCatalog(EMPTY);
      });
    return () => {
      alive = false;
    };
  }, [workspaceId, allowedKey]);

  return catalog;
}
