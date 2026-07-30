"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type McpSurface,
  deleteMcpSurfaceServer,
  loadMcpSurface,
  writeMcpSurface,
} from "@/components/mcp/surface";
import {
  authorizeSpaceMcpServer,
  type McpServerConfig,
  type McpStatusRow,
  type McpStoreState,
  type McpUserView,
} from "@/lib/mcp-api";
import { describeMcpError } from "@/lib/mcp-store";

/**
 * State + handlers behind an MCP server manager screen.
 *
 * Mutations (toggle, delete, save) are expressed as the registry the screen
 * wants to end up with; the surface's helpers translate that into whatever
 * writes its API takes and answer with fresh connection status, so one round
 * trip keeps the rows and their badges in sync.
 */
export function useMcpServers(surface: McpSurface) {
  const { t } = useTranslation();

  const [servers, setServers] = useState<Record<
    string,
    McpServerConfig
  > | null>(null);
  const [statusRows, setStatusRows] = useState<McpStatusRow[]>([]);
  /** The per-user extras (secret markers, rejects, deployment view, cap). */
  const [userView, setUserView] = useState<McpUserView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // Editing key: a server name for edit, "" for the "add new" form, or null
  // when no editor is open.
  const [editingKey, setEditingKey] = useState<string | null>(null);

  /**
   * Adopt a full state snapshot — a load, a write's response, or a write made
   * outside this hook (a catalog install). Every one of those endpoints answers
   * with the same shape, so none of them needs a follow-up read.
   */
  const applyState = useCallback((state: McpStoreState) => {
    setServers(state.servers);
    setStatusRows(state.status);
    setUserView(state.user);
  }, []);

  const load = useCallback(async () => {
    try {
      applyState(await loadMcpSurface(surface));
      setLoadError(null);
    } catch (err) {
      setLoadError(describeMcpError(err, t));
    }
  }, [surface, t, applyState]);

  useEffect(() => {
    void load();
  }, [load]);

  const statusByName = useMemo(() => {
    const map = new Map<string, McpStatusRow>();
    for (const row of statusRows) map.set(row.name, row);
    return map;
  }, [statusRows]);

  const persist = useCallback(
    async (next: Record<string, McpServerConfig>) => {
      setSaving(true);
      setSaveError(null);
      try {
        // Adopt what the backend reports rather than `next`: on the per-user
        // surface the file is the authority, and a partially applied write must
        // not leave the rows showing an intent that never landed.
        applyState(await writeMcpSurface(surface, servers ?? {}, next));
        return true;
      } catch (err) {
        setSaveError(describeMcpError(err, t));
        // A refused write may still have applied an earlier step of the diff.
        await load();
        return false;
      } finally {
        setSaving(false);
      }
    },
    [surface, servers, t, load, applyState],
  );

  const toggleExpanded = useCallback((name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const toggleEnabled = useCallback(
    async (name: string) => {
      if (!servers || saving) return;
      const current = servers[name];
      if (!current) return;
      const next = {
        ...servers,
        [name]: { ...current, enabled: !current.enabled },
      };
      await persist(next);
    },
    [servers, saving, persist],
  );

  const remove = useCallback(
    async (name: string) => {
      if (!servers || saving) return;
      if (
        typeof window !== "undefined" &&
        !window.confirm(t('Delete MCP server "{{name}}"?', { name }))
      ) {
        return;
      }
      const next = { ...servers };
      delete next[name];
      if (editingKey === name) setEditingKey(null);
      await persist(next);
    },
    [servers, saving, t, editingKey, persist],
  );

  /**
   * Delete an entry the store refuses to connect (a hand-edited stdio server).
   *
   * It is absent from `servers`, so the diff `remove()` performs would issue no
   * request at all — leaving the user looking at a row they cannot get rid of.
   * Only meaningful on a per-server surface; the registry surface has no such
   * entries because it accepts stdio in the first place.
   */
  const removeRejected = useCallback(
    async (name: string) => {
      if (saving || surface.writes !== "per-server") return;
      if (
        typeof window !== "undefined" &&
        !window.confirm(t('Delete MCP server "{{name}}"?', { name }))
      ) {
        return;
      }
      setSaving(true);
      setSaveError(null);
      try {
        applyState(await deleteMcpSurfaceServer(surface, name));
      } catch (err) {
        setSaveError(describeMcpError(err, t));
      } finally {
        setSaving(false);
      }
    },
    [surface, saving, t, applyState],
  );

  /**
   * Grant an OAuth-backed server its authorization.
   *
   * The consent screen belongs to the provider, so it opens in a new tab; when it
   * redirects back the app's callback route completes the exchange server-side.
   * We reload after a beat rather than polling: the person is in the other tab,
   * and the state they come back to has to be the real one.
   */
  const authorize = useCallback(
    async (name: string) => {
      if (saving) return;
      setSaving(true);
      setSaveError(null);
      try {
        const url = await authorizeSpaceMcpServer(surface.basePath, name);
        if (!url) throw new Error("no authorization URL");
        if (typeof window !== "undefined") window.open(url, "_blank", "noopener");
      } catch (err) {
        setSaveError(describeMcpError(err, t));
      } finally {
        setSaving(false);
      }
    },
    [surface.basePath, saving, t],
  );

  const save = useCallback(
    async (originalName: string | "", name: string, cfg: McpServerConfig) => {
      if (!servers) return false;
      const next = { ...servers };
      // Rename: drop the old key when editing under a new name.
      if (originalName && originalName !== name) delete next[originalName];
      next[name] = cfg;
      const ok = await persist(next);
      if (ok) setEditingKey(null);
      return ok;
    },
    [servers, persist],
  );

  const startAdding = useCallback(() => setEditingKey(""), []);
  const cancelEditing = useCallback(() => setEditingKey(null), []);
  const toggleEditing = useCallback((name: string) => {
    setEditingKey((prev) => (prev === name ? null : name));
  }, []);

  const serverNames = useMemo(
    () => (servers ? Object.keys(servers).sort() : []),
    [servers],
  );

  return {
    servers,
    serverNames,
    statusByName,
    userView,
    loadError,
    saveError,
    saving,
    expanded,
    editingKey,
    reload: load,
    applyState,
    toggleExpanded,
    toggleEnabled,
    toggleEditing,
    startAdding,
    cancelEditing,
    remove,
    removeRejected,
    save,
    authorize,
  };
}
