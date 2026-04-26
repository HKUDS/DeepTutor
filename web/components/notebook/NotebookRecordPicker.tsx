"use client";

import { useEffect } from "react";
import { Layers, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import NotebookSelector from "@/components/notebook/NotebookSelector";
import { useNotebookSelection } from "@/components/notebook/useNotebookSelection";
import type { SelectedRecord } from "@/lib/notebook-selection-types";

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
  actionLabel = "Use Selected Records ({n})",
}: NotebookRecordPickerProps) {
  const { t } = useTranslation();
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
    <div className="fixed inset-0 z-[85] flex items-end justify-center bg-[var(--background)]/65 p-0 backdrop-blur-md sm:items-center sm:p-4">
      <div className="surface-card flex max-h-[92dvh] w-full max-w-4xl flex-col overflow-hidden rounded-t-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)] shadow-[0_22px_70px_rgba(0,0,0,0.18)] sm:rounded-2xl">
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-[var(--border)] px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <div className="mb-1 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--primary)]">
              <Layers className="h-3 w-3" />
              {t("Notebook Reference")}
            </div>
            <h2 className="text-lg font-semibold text-[var(--foreground)]">
              {t("Select Notebook Records")}
            </h2>
            <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
              {t(
                "Choose records across one or more notebooks to ground the next request.",
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            aria-label={t("Close")}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto bg-[var(--background)]/40 p-4 sm:p-5">
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
