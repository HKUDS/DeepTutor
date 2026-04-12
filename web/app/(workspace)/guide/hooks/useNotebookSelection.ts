import { useState, useCallback } from "react";
import { listCategories, listNotebookEntries } from "@/lib/notebook-api";
import { Notebook, NotebookRecord, SelectedRecord } from "../types";

/**
 * Hook for managing notebook and record selection
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
    try {
      const categories = await listCategories();
      const notebooksWithRecords = categories
        .filter((cat) => (cat.entry_count ?? 0) > 0)
        .map(
          (cat): Notebook => ({
            id: String(cat.id),
            name: cat.name,
            description: "",
            record_count: cat.entry_count ?? 0,
            color: "",
          }),
        );
      setNotebooks(notebooksWithRecords);
      setLoadingNotebooks(false);
    } catch (err) {
      console.error("Failed to fetch notebooks:", err);
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
        const data = await listNotebookEntries({ category_id: Number(notebookId) });
        const records = (data.items || []).map(
          (entry): NotebookRecord => ({
            id: String(entry.id),
            title: entry.question,
            summary: entry.explanation,
            user_query: entry.question,
            output: entry.correct_answer,
            type: entry.question_type,
          }),
        );
        setNotebookRecordsMap((prev) =>
          new Map(prev).set(notebookId, records),
        );
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
