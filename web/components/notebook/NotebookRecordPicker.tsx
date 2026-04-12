"use client";

import { useEffect } from "react";
import { X } from "lucide-react";
import NotebookSelector from "@/app/(workspace)/guide/components/NotebookSelector";
import { useNotebookSelection } from "@/app/(workspace)/guide/hooks/useNotebookSelection";
import type { SelectedRecord } from "@/app/(workspace)/guide/types";

interface NotebookRecordPickerProps {
  open: boolean;
  onClose: () => void;
  onApply: (records: SelectedRecord[]) => void;
  actionLabel?: string;
}

export default function NotebookRecordPicker({
  open,
  onClose,
  onApply,
  actionLabel = "Use selected records ({n})",
}: NotebookRecordPickerProps) {
  const {
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
  } = useNotebookSelection();

  useEffect(() => {
    if (!open) return;
    void fetchNotebooks();
  }, [fetchNotebooks, open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-md">
      <div className="w-full max-w-4xl overflow-hidden rounded-[22px] border border-slate-200 bg-white shadow-[0_22px_70px_rgba(15,23,42,0.24)] dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-700">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              Select Notebook Records
            </h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Select records from one or more notebooks to provide context for the next request.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="bg-slate-50/70 p-5 dark:bg-slate-950/40">
          <NotebookSelector
            notebooks={notebooks}
            expandedNotebooks={expandedNotebooks}
            notebookRecordsMap={notebookRecordsMap}
            selectedRecords={selectedRecords}
            loadingNotebooks={loadingNotebooks}
            loadingRecordsFor={loadingRecordsFor}
            isLoading={false}
            onToggleExpanded={toggleNotebookExpanded}
            onToggleRecord={toggleRecordSelection}
            onSelectAll={selectAllFromNotebook}
            onDeselectAll={deselectAllFromNotebook}
            onClearAll={clearAllSelections}
            onCreateSession={() => {
              onApply(Array.from(selectedRecords.values()) as SelectedRecord[]);
              onClose();
            }}
            actionLabel={actionLabel}
          />
        </div>
      </div>
    </div>
  );
}
