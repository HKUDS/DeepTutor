"use client";

import {
  ArrowDownNarrowWide,
  ArrowUpNarrowWide,
  ListChecks,
  Rows3,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/shared/ui/Tooltip";
import {
  ANNOTATION_SWATCH,
  annotationColorLabel,
  type AnnotationColor,
} from "@/lib/reading-api";
import { sortLabel, type AnnotationSort } from "@/lib/reading-mark-list";

/**
 * The search, order and colour controls above the list.
 *
 * Split out of the list: three independent filters plus a selection toggle is
 * a control strip, not part of deciding which rows to draw.
 */
export function AnnotationToolbar({
  showSearch,
  query,
  sort,
  colours,
  appliedColor,
  selectionSelecting,
  onQuery,
  onCycleSort,
  onToggleColor,
  onStartSelection,
  onStopSelection,
}: {
  showSearch: boolean;
  query: string;
  sort: AnnotationSort;
  colours: AnnotationColor[];
  appliedColor: string | null;
  selectionSelecting: boolean;
  onQuery: (value: string) => void;
  onCycleSort: () => void;
  onToggleColor: (color: AnnotationColor | null) => void;
  onStartSelection: () => void;
  onStopSelection: () => void;
}) {
  const { t } = useTranslation();
  return (
    <>
{showSearch && (
  <div className="flex shrink-0 items-center gap-1 px-2.5 pt-2">
    <div className="relative min-w-0 flex-1">
      <Search
        size={12}
        aria-hidden
        className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
      />
      <input
        type="search"
        value={query}
        onChange={(event) => onQuery(event.target.value)}
        placeholder={t("Search annotations…")}
        aria-label={t("Search annotations…")}
        className="h-7 w-full rounded-md border border-[var(--border)] bg-[var(--background)] pl-7 pr-2 text-[11.5px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
      />
    </div>
    {/* One button cycling three orders, rather than a menu: the states
        are few, and the icon's direction says which one is active. */}
    {(
      <Tooltip label={selectionSelecting ? t("Done") : t("Select annotations")} side="top">
        <button
          type="button"
          aria-label={selectionSelecting ? t("Done") : t("Select annotations")}
          aria-pressed={selectionSelecting}
          data-testid="annotation-select-toggle"
          onClick={() => (selectionSelecting ? onStopSelection() : onStartSelection())}
          className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] ${
            selectionSelecting
              ? "border-[var(--primary)] text-[var(--primary)]"
              : "border-[var(--border)]"
          }`}
        >
          <ListChecks size={13} aria-hidden />
        </button>
      </Tooltip>
    )}
    <Tooltip label={t(sortLabel(sort))} side="top">
      <button
        type="button"
        aria-label={t(sortLabel(sort))}
        data-testid="annotation-sort"
        onClick={() => onCycleSort()}
        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
      >
        {sort === "newest" ? (
          <ArrowDownNarrowWide size={13} aria-hidden />
        ) : sort === "oldest" ? (
          <ArrowUpNarrowWide size={13} aria-hidden />
        ) : (
          <Rows3 size={13} aria-hidden />
        )}
      </button>
    </Tooltip>
  </div>
)}

{colours.length > 1 && (
  <div
    role="group"
    aria-label={t("Filter by colour")}
    className="flex shrink-0 items-center gap-1 px-2.5 pt-1.5"
  >
    {colours.map((color) => (
      <Tooltip key={color} label={t(annotationColorLabel(color))} side="top">
        <button
          type="button"
          aria-label={t(annotationColorLabel(color))}
          aria-pressed={appliedColor === color}
          data-testid={`annotation-color-filter-${color}`}
          onClick={() =>
            onToggleColor(appliedColor === color ? null : (color as AnnotationColor))
          }
          className={`h-3.5 w-3.5 rounded-full border transition ${
            appliedColor === color
              ? "border-[var(--foreground)] scale-110"
              : "border-black/10 hover:scale-105"
          }`}
          style={{ background: ANNOTATION_SWATCH[color as AnnotationColor] }}
        />
      </Tooltip>
    ))}
    {appliedColor !== null && (
      <button
        type="button"
        onClick={() => onToggleColor(null)}
        className="ml-0.5 rounded px-1 text-[10px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
      >
        {t("All colours")}
      </button>
    )}
  </div>
)}
    </>
  );
}
