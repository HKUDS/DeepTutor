import { useState, useCallback } from "react";
import { listNotebooks, getNotebook } from "@/lib/notebook-api";
import {
  Notebook,
  NotebookRecord,
  SelectedRecord,
} from "@/lib/notebook-selection-types";

/**
 * Hook for managing notebook and record selection across notebook pickers.
 *
 * Backed by the real notebook system (`/api/v1/notebook/*`) so that records
 * saved via Save-to-Notebook from any surface are immediately discoverable
 * here as references.
 */
export function useNotebookSelection() {
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [expandedNotebooks, setExpandedNotebooks] = useState<Set<string>>(
    new Set(),
  );
  const [notebookRecordsMap, setNotebookRecordsMap] = useState<
    Map<string, NotebookRecord[]>
  >(new Map());
  const [selectedRecords, setSelectedRecords] = useState<
    Map<string, SelectedRecord>
  >(new Map());
  const [loadingNotebooks, setLoadingNotebooks] = useState(true);
  const [loadingRecordsFor, setLoadingRecordsFor] = useState<Set<string>>(
    new Set(),
  );

  const fetchNotebooks = useCallback(async () => {
    setLoadingNotebooks(true);
    try {
      const data = await listNotebooks();
      const items = data
        .filter((nb) => (nb.record_count ?? 0) > 0)
        .map(
          (nb): Notebook => ({
            id: String(nb.id),
            name: nb.name,
            description: nb.description ?? "",
            record_count: nb.record_count ?? 0,
            color: nb.color ?? "",
          }),
        );
      setNotebooks(items);
    } catch (err) {
      console.error("Failed to fetch notebooks:", err);
      setNotebooks([]);
    } finally {
      setLoadingNotebooks(false);
    }
  }, []);

  const fetchNotebookRecords = useCallback(
    async (notebookId: string) => {
      if (notebookRecordsMap.has(notebookId)) return;

      setLoadingRecordsFor((prev) => {
        const newSet = new Set(prev);
        newSet.add(notebookId);
        return newSet;
      });
      try {
        const detail = await getNotebook(notebookId);
        const records = (detail.records || []).map(
          (rec): NotebookRecord => ({
            id: String(rec.id),
            title: rec.title,
            summary: rec.summary,
            user_query: rec.user_query,
            output: rec.output,
            type: String(rec.type),
          }),
        );
        setNotebookRecordsMap((prev) => new Map(prev).set(notebookId, records));
      } catch (err) {
        console.error("Failed to fetch notebook records:", err);
      } finally {
        setLoadingRecordsFor((prev) => {
          const newSet = new Set(prev);
          newSet.delete(notebookId);
          return newSet;
        });
      }
    },
    [notebookRecordsMap],
  );

  const toggleNotebookExpanded = useCallback(
    (notebookId: string) => {
      const notebook = notebooks.find((nb) => nb.id === notebookId);
      if (!notebook) return;

      setExpandedNotebooks((prev) => {
        const newSet = new Set(prev);
        if (newSet.has(notebookId)) {
          newSet.delete(notebookId);
        } else {
          newSet.add(notebookId);
          fetchNotebookRecords(notebookId);
        }
        return newSet;
      });
    },
    [notebooks, fetchNotebookRecords],
  );

  const toggleRecordSelection = useCallback(
    (record: NotebookRecord, notebookId: string, notebookName: string) => {
      setSelectedRecords((prev) => {
        const newMap = new Map(prev);
        if (newMap.has(record.id)) {
          newMap.delete(record.id);
        } else {
          newMap.set(record.id, { ...record, notebookId, notebookName });
        }
        return newMap;
      });
    },
    [],
  );

  const selectAllFromNotebook = useCallback(
    (notebookId: string, notebookName: string) => {
      const records = notebookRecordsMap.get(notebookId) || [];
      setSelectedRecords((prev) => {
        const newMap = new Map(prev);
        records.forEach((r) =>
          newMap.set(r.id, { ...r, notebookId, notebookName }),
        );
        return newMap;
      });
    },
    [notebookRecordsMap],
  );

  const deselectAllFromNotebook = useCallback(
    (notebookId: string) => {
      const records = notebookRecordsMap.get(notebookId) || [];
      const recordIds = new Set(records.map((r) => r.id));
      setSelectedRecords((prev) => {
        const newMap = new Map(prev);
        recordIds.forEach((id) => newMap.delete(id));
        return newMap;
      });
    },
    [notebookRecordsMap],
  );

  const clearAllSelections = useCallback(() => {
    setSelectedRecords(new Map());
  }, []);

  return {
    notebooks,
    expandedNotebooks,
    notebookRecordsMap,
    selectedRecords,
    loadingNotebooks,
    loadingRecordsFor,
    fetchNotebooks,
    toggleNotebookExpanded,
    toggleRecordSelection,
    selectAllFromNotebook,
    deselectAllFromNotebook,
    clearAllSelections,
  };
}
