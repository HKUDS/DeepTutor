"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createNotebook,
  deleteNotebook,
  deleteNotebookRecord,
  getNotebook,
  listNotebooks,
  relocateNotebookRecord,
  updateNotebook,
  updateNotebookRecord,
  type NotebookRecordItem,
  type NotebookSummary,
} from "@/lib/notebook-api";

/**
 * Every notebook read/write the console needs, in one place.
 *
 * The UI components below stay presentational: they render what this hook
 * exposes and call back into it. Mutations update local state optimistically
 * where the server response is predictable (rename, delete) and re-fetch
 * where it is not (create, move), so the list never shows a stale count.
 */

export interface NotebookLibrary {
  notebooks: NotebookSummary[];
  selectedId: string | null;
  selected: NotebookDetailState | null;
  loading: boolean;
  detailLoading: boolean;
  error: string | null;
  detailError: string | null;
  select: (notebookId: string | null) => void;
  reload: () => Promise<void>;
  create: (name: string, description: string, color?: string) => Promise<string | null>;
  rename: (
    notebookId: string,
    changes: { name?: string; description?: string; color?: string },
  ) => Promise<void>;
  remove: (notebookId: string) => Promise<void>;
  editRecord: (
    recordId: string,
    changes: { title?: string; summary?: string; output?: string },
  ) => Promise<void>;
  removeRecord: (recordId: string) => Promise<void>;
  relocateRecord: (
    recordId: string,
    targetNotebookId: string,
    mode: "move" | "copy",
  ) => Promise<void>;
}

export interface NotebookDetailState extends NotebookSummary {
  records: NotebookRecordItem[];
}

function messageOf(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export function useNotebookLibrary(
  initialId?: string | null,
): NotebookLibrary {
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(
    initialId ?? null,
  );
  const [selected, setSelected] = useState<NotebookDetailState | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const previousRouteIdRef = useRef(initialId ?? null);

  // Detail fetches are racy — clicking through the list fires several. Only
  // the newest one is allowed to write state, otherwise a slow earlier
  // response can overwrite the notebook the user is actually looking at.
  const detailRequestRef = useRef(0);

  const loadDetail = useCallback(async (notebookId: string) => {
    const requestId = ++detailRequestRef.current;
    setDetailLoading(true);
    setDetailError(null);
    try {
      const data = await getNotebook(notebookId);
      if (detailRequestRef.current !== requestId) return;
      setSelected({ ...data, records: data.records ?? [] });
    } catch (err) {
      if (detailRequestRef.current !== requestId) return;
      setSelected(null);
      setDetailError(messageOf(err));
    } finally {
      if (detailRequestRef.current === requestId) setDetailLoading(false);
    }
  }, []);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const next = await listNotebooks();
      setNotebooks(next);
      // Only the route opens a notebook: `/notebooks` itself is the list.
      setSelectedId((current) =>
        current &&
        (current === previousRouteIdRef.current ||
          next.some((n) => n.id === current))
          ? current
          : null,
      );
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // App Router can reuse this client component while only the dynamic segment
  // changes. Treat that segment as authoritative so browser back/forward and
  // direct notebook links update the open record without a remount.
  useEffect(() => {
    const routeId = initialId ?? null;
    if (previousRouteIdRef.current === routeId) return;
    previousRouteIdRef.current = routeId;
    setSelectedId(routeId);
  }, [initialId]);

  useEffect(() => {
    if (!selectedId) {
      // Bump the request counter as well as clearing. `loadDetail` stamps each
      // fetch and drops its own result if a *newer* one started — but clearing
      // starts no fetch, so without this an in-flight response lands after the
      // clear and puts the notebook straight back on screen.
      detailRequestRef.current += 1;
      setSelected(null);
      setDetailError(null);
      setDetailLoading(false);
      return;
    }
    void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  const select = useCallback((notebookId: string | null) => {
    setSelectedId(notebookId);
  }, []);

  const create = useCallback(
    async (name: string, description: string, color?: string) => {
      const trimmed = name.trim();
      if (!trimmed) return null;
      const created = await createNotebook({
        name: trimmed,
        description: description.trim(),
        ...(color ? { color } : {}),
      });
      await reload();
      setSelectedId(created.id);
      return created.id;
    },
    [reload],
  );

  const rename = useCallback(
    async (
      notebookId: string,
      changes: { name?: string; description?: string; color?: string },
    ) => {
      const updated = await updateNotebook(notebookId, changes);
      setNotebooks((prev) =>
        prev.map((n) => (n.id === notebookId ? { ...n, ...updated } : n)),
      );
      setSelected((prev) =>
        prev && prev.id === notebookId ? { ...prev, ...updated } : prev,
      );
    },
    [],
  );

  const remove = useCallback(
    async (notebookId: string) => {
      await deleteNotebook(notebookId);
      setNotebooks((prev) => prev.filter((n) => n.id !== notebookId));
      setSelectedId((current) => (current === notebookId ? null : current));
    },
    [],
  );

  // Keep the sidebar's record count honest after any record-level change
  // without paying for a full list refetch.
  const adjustCount = useCallback((notebookId: string, delta: number) => {
    setNotebooks((prev) =>
      prev.map((n) =>
        n.id === notebookId
          ? { ...n, record_count: Math.max(0, (n.record_count ?? 0) + delta) }
          : n,
      ),
    );
  }, []);

  const editRecord = useCallback(
    async (
      recordId: string,
      changes: { title?: string; summary?: string; output?: string },
    ) => {
      if (!selectedId) return;
      const updated = await updateNotebookRecord(selectedId, recordId, changes);
      setSelected((prev) =>
        prev
          ? {
              ...prev,
              records: prev.records.map((r) =>
                r.id === recordId ? { ...r, ...updated } : r,
              ),
            }
          : prev,
      );
    },
    [selectedId],
  );

  const removeRecord = useCallback(
    async (recordId: string) => {
      if (!selectedId) return;
      await deleteNotebookRecord(selectedId, recordId);
      setSelected((prev) =>
        prev
          ? { ...prev, records: prev.records.filter((r) => r.id !== recordId) }
          : prev,
      );
      adjustCount(selectedId, -1);
    },
    [selectedId, adjustCount],
  );

  const relocateRecord = useCallback(
    async (
      recordId: string,
      targetNotebookId: string,
      mode: "move" | "copy",
    ) => {
      if (!selectedId) return;
      await relocateNotebookRecord(
        selectedId,
        recordId,
        targetNotebookId,
        mode,
      );
      if (mode === "move") {
        setSelected((prev) =>
          prev
            ? {
                ...prev,
                records: prev.records.filter((r) => r.id !== recordId),
              }
            : prev,
        );
        adjustCount(selectedId, -1);
      }
      // A multi-collection save can already exist at the destination.
      // Re-read counts instead of inventing an additional record.
      await reload();
    },
    [selectedId, adjustCount, reload],
  );

  return useMemo(
    () => ({
      notebooks,
      selectedId,
      selected,
      loading,
      detailLoading,
      error,
      detailError,
      select,
      reload,
      create,
      rename,
      remove,
      editRecord,
      removeRecord,
      relocateRecord,
    }),
    [
      notebooks,
      selectedId,
      selected,
      loading,
      detailLoading,
      error,
      detailError,
      select,
      reload,
      create,
      rename,
      remove,
      editRecord,
      removeRecord,
      relocateRecord,
    ],
  );
}
