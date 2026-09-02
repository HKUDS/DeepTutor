"use client";

import { useTranslation } from "react-i18next";
import {
  ArrowDownWideNarrow,
  Loader2,
  Search,
  Settings2,
  X,
} from "lucide-react";
import type {
  AssessmentSource,
  QuestionBankMaterial,
  ScoreTrend,
} from "@/lib/notebook-api";
import type { BankSort, ReviewFilters } from "./useQuestionBank";

interface BankToolbarProps {
  search: string;
  sort: BankSort;
  refreshing: boolean;
  managerOpen: boolean;
  filters: ReviewFilters;
  materials: QuestionBankMaterial[];
  onSearchChange: (value: string) => void;
  onSortChange: (sort: BankSort) => void;
  onToggleManager: () => void;
  onFiltersChange: (filters: ReviewFilters) => void;
}

/**
 * Search + sort + the entry point to category management.
 *
 * Search is the other half of "I can't organize this": with a few hundred
 * entries, filing the right ones starts with finding them.
 */
export default function BankToolbar({
  search,
  sort,
  refreshing,
  managerOpen,
  filters,
  materials,
  onSearchChange,
  onSortChange,
  onToggleManager,
  onFiltersChange,
}: BankToolbarProps) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-[200px] flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={t("Search questions and answers…")}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] py-1.5 pl-8 pr-8 text-[12.5px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)]/50"
        />
        {refreshing ? (
          <Loader2 className="absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-[var(--muted-foreground)]" />
        ) : search ? (
          <button
            type="button"
            onClick={() => onSearchChange("")}
            title={t("Clear")}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>

      <button
        type="button"
        onClick={() => onSortChange(sort === "recent" ? "oldest" : "recent")}
        title={t("Toggle sort order")}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
      >
        <ArrowDownWideNarrow
          className={`h-3.5 w-3.5 transition-transform ${sort === "oldest" ? "rotate-180" : ""}`}
        />
        {sort === "recent" ? t("Newest first") : t("Oldest first")}
      </button>

      <select
        value={filters.source}
        onChange={(event) =>
          onFiltersChange({
            ...filters,
            source: event.target.value as AssessmentSource | "",
            materialId: "",
          })
        }
        aria-label={t("Source")}
        className="h-[34px] rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 text-[12px] text-[var(--foreground)] outline-none"
      >
        <option value="">{t("All Sources")}</option>
        <option value="deep_question">{t("Deep Question")}</option>
        <option value="mastery_path">{t("Mastery Path")}</option>
        <option value="immersive_reading">{t("Immersive Reading")}</option>
        <option value="book">{t("Book")}</option>
      </select>

      <select
        value={filters.materialId}
        onChange={(event) =>
          onFiltersChange({ ...filters, materialId: event.target.value })
        }
        aria-label={t("Material")}
        disabled={materials.length === 0}
        className="h-[34px] max-w-[180px] rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 text-[12px] text-[var(--foreground)] outline-none disabled:opacity-50"
      >
        <option value="">{t("All Materials")}</option>
        {materials
          .filter((item) => !filters.source || item.source === filters.source)
          .map((item) => (
            <option
              key={`${item.source}:${item.material_id}`}
              value={item.material_id}
            >
              {item.material_title}
            </option>
          ))}
      </select>

      <select
        value={filters.scoreTrend}
        onChange={(event) =>
          onFiltersChange({
            ...filters,
            scoreTrend: event.target.value as ScoreTrend | "",
          })
        }
        aria-label={t("Score Trend")}
        className="h-[34px] rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 text-[12px] text-[var(--foreground)] outline-none"
      >
        <option value="">{t("All Trends")}</option>
        <option value="new">{t("First Attempt")}</option>
        <option value="improved">{t("Improved")}</option>
        <option value="declined">{t("Declined")}</option>
        <option value="unchanged">{t("Unchanged")}</option>
      </select>

      <button
        type="button"
        onClick={onToggleManager}
        title={t("Manage Categories")}
        className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] transition-colors ${
          managerOpen
            ? "border-[var(--primary)]/40 bg-[var(--primary)]/10 text-[var(--primary)]"
            : "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
        }`}
      >
        <Settings2 className="h-3.5 w-3.5" />
        {t("Manage Categories")}
      </button>
    </div>
  );
}
