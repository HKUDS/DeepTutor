"use client";

import { useTranslation } from "react-i18next";
import { CheckSquare, FolderMinus, X } from "lucide-react";
import type { NotebookCategory } from "@/lib/notebook-api";
import CategoryMenu from "./CategoryMenu";
import type { BankScope } from "./useQuestionBank";

interface BankSelectionBarProps {
  count: number;
  visibleCount: number;
  scope: BankScope;
  categories: NotebookCategory[];
  onSelectAll: () => void;
  onClear: () => void;
  onFile: (categoryId: number) => Promise<boolean>;
  onCreateAndFile: (name: string) => Promise<boolean>;
  onUnfileFromCurrent: () => Promise<boolean>;
}

/**
 * Floating bar for acting on a multi-selection.
 *
 * Appears only once something is selected, so the default reading view
 * stays clean; "remove from this category" is offered only while actually
 * inside a category, where it is the one unambiguous meaning.
 */
export default function BankSelectionBar({
  count,
  visibleCount,
  scope,
  categories,
  onSelectAll,
  onClear,
  onFile,
  onCreateAndFile,
  onUnfileFromCurrent,
}: BankSelectionBarProps) {
  const { t } = useTranslation();
  if (count === 0) return null;

  return (
    <div className="sticky bottom-4 z-20 mx-auto flex w-fit max-w-full flex-wrap items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 shadow-lg">
      <span className="text-[12.5px] font-medium text-[var(--foreground)]">
        {count} {t("selected")}
      </span>

      {count < visibleCount && (
        <button
          type="button"
          onClick={onSelectAll}
          className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
        >
          <CheckSquare className="h-3.5 w-3.5" />
          {t("Select all")}
        </button>
      )}

      <span className="h-4 w-px bg-[var(--border)]" />

      <CategoryMenu
        categories={categories}
        label={t("Add to category")}
        align="left"
        direction="up"
        variant="outlined"
        onPick={onFile}
        onCreate={onCreateAndFile}
      />

      {scope.kind === "category" && (
        <button
          type="button"
          onClick={() => void onUnfileFromCurrent()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2 py-1.5 text-[11.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
        >
          <FolderMinus className="h-3.5 w-3.5" />
          {t("Remove from category")}
        </button>
      )}

      <button
        type="button"
        onClick={onClear}
        title={t("Clear selection")}
        className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
