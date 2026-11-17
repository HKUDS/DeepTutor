"use client";

import {
  Loader2,
  ChevronRight,
  ChevronDown,
  Check,
  NotebookPen,
} from "lucide-react";
import {
  Notebook,
  NotebookRecord,
  SelectedRecord,
  getTypeColor,
} from "@/lib/notebook-selection-types";
import { useTranslation } from "react-i18next";

interface NotebookSelectorProps {
  notebooks: Notebook[];
  expandedNotebooks: Set<string>;
  notebookRecordsMap: Map<string, NotebookRecord[]>;
  selectedRecords: Map<string, SelectedRecord>;
  loadingNotebooks: boolean;
  loadingRecordsFor: Set<string>;
  isLoading: boolean;
  onToggleExpanded: (notebookId: string) => void;
  onToggleRecord: (
    record: NotebookRecord,
    notebookId: string,
    notebookName: string,
  ) => void;
  onSelectAll: (notebookId: string, notebookName: string) => void;
  onDeselectAll: (notebookId: string) => void;
  onClearAll: () => void;
  onCreateSession: () => void;
  actionLabel?: string;
}

export default function NotebookSelector({
  notebooks,
  expandedNotebooks,
  notebookRecordsMap,
  selectedRecords,
  loadingNotebooks,
  loadingRecordsFor,
  isLoading,
  onToggleExpanded,
  onToggleRecord,
  onSelectAll,
  onDeselectAll,
  onClearAll,
  onCreateSession,
  actionLabel,
}: NotebookSelectorProps) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--card)] px-4 py-3.5">
        <h2 className="flex items-center gap-2 text-[14px] font-semibold text-[var(--foreground)]">
          <NotebookPen className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
          {t("Select Source (Cross-Notebook)")}
        </h2>
        {selectedRecords.size > 0 && (
          <button
            onClick={onClearAll}
            className="rounded-md px-2 py-1 text-xs text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--destructive)]"
          >
            {t("Clear")} ({selectedRecords.size})
          </button>
        )}
      </div>

      <div className="max-h-[460px] flex-1 overflow-y-auto px-2 py-2">
        {loadingNotebooks ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : notebooks.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-sm text-[var(--muted-foreground)]">
            <NotebookPen className="h-5 w-5 text-[var(--muted-foreground)]/60" />
            <span>{t("No notebooks with records found")}</span>
            <span className="text-[11px] text-[var(--muted-foreground)]/80">
              {t("Save a chat result first to populate a notebook.")}
            </span>
          </div>
        ) : (
          <div className="space-y-2">
            {notebooks.map((notebook) => {
              const isExpanded = expandedNotebooks.has(notebook.id);
              const records = notebookRecordsMap.get(notebook.id) || [];
              const isLoadingRecords = loadingRecordsFor.has(notebook.id);
              const selectedFromThis = records.filter((r) =>
                selectedRecords.has(r.id),
              ).length;

              return (
                <div
                  key={notebook.id}
                  className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)]/60"
                >
                  {/* Notebook Header */}
                  <button
                    type="button"
                    className="flex w-full cursor-pointer items-center gap-2 px-3 py-2.5 text-start transition-colors hover:bg-[var(--muted)]/50"
                    onClick={() => onToggleExpanded(notebook.id)}
                  >
                    {isExpanded ? (
                      <ChevronDown className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
                    )}
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{
                        backgroundColor: notebook.color || "var(--primary)",
                      }}
                    />
                    <span className="flex-1 truncate text-[13px] font-medium text-[var(--foreground)]">
                      {notebook.name}
                    </span>
                    <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
                      {selectedFromThis > 0 && (
                        <span className="font-medium text-[var(--primary)]">
                          {selectedFromThis}/
                        </span>
                      )}
                      {notebook.record_count}
                    </span>
                  </button>

                  {/* Records List */}
                  {isExpanded && (
                    <div className="border-t border-[var(--border)] bg-[var(--background)]/30 px-3 pb-3 pt-2">
                      {isLoadingRecords ? (
                        <div className="flex items-center justify-center py-4">
                          <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
                        </div>
                      ) : records.length === 0 ? (
                        <div className="py-3 text-center text-[12px] text-[var(--muted-foreground)]">
                          {t("No records")}
                        </div>
                      ) : (
                        <>
                          <div className="mb-2 flex gap-3 text-[11px]">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                onSelectAll(notebook.id, notebook.name);
                              }}
                              className="text-[var(--primary)] transition-colors hover:opacity-80"
                            >
                              {t("Select All")}
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                onDeselectAll(notebook.id);
                              }}
                              className="text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                            >
                              {t("Deselect")}
                            </button>
                          </div>
                          <div className="space-y-1.5">
                            {records.map((record) => {
                              const isSelected = selectedRecords.has(record.id);
                              return (
                                <div
                                  key={record.id}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onToggleRecord(
                                      record,
                                      notebook.id,
                                      notebook.name,
                                    );
                                  }}
                                  className={`cursor-pointer rounded-lg border p-2.5 transition-all ${
                                    isSelected
                                      ? "border-[var(--primary)]/40 bg-[var(--primary)]/8"
                                      : "border-transparent hover:border-[var(--border)] hover:bg-[var(--muted)]/40"
                                  }`}
                                >
                                  <div className="flex items-start gap-2">
                                    <div
                                      className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                                        isSelected
                                          ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                                          : "border-[var(--border)]"
                                      }`}
                                    >
                                      {isSelected && (
                                        <Check className="h-2.5 w-2.5" />
                                      )}
                                    </div>
                                    <div className="min-w-0 flex-1">
                                      <div className="flex items-center gap-2">
                                        <span
                                          className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${getTypeColor(record.type)}`}
                                        >
                                          {record.type}
                                        </span>
                                        <span className="truncate text-[12px] text-[var(--foreground)]">
                                          {record.title}
                                        </span>
                                      </div>
                                      {record.summary && (
                                        <p className="mt-1.5 line-clamp-2 text-[11px] leading-5 text-[var(--muted-foreground)]">
                                          {record.summary}
                                        </p>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Apply Button */}
      <div className="border-t border-[var(--border)] bg-[var(--card)] p-4">
        <button
          onClick={onCreateSession}
          disabled={isLoading || selectedRecords.size === 0}
          className="btn-primary flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isLoading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("Generating...")}
            </>
          ) : (
            (actionLabel || t("Use Selected Records ({n})")).replace(
              "{n}",
              String(selectedRecords.size),
            )
          )}
        </button>
      </div>
    </div>
  );
}
