"use client";

import dynamic from "next/dynamic";
import { useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowDownNarrowWide,
  ArrowUpNarrowWide,
  Bookmark,
  Bot,
  Copy,
  Highlighter,
  ListChecks,
  Pencil,
  Rows3,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/shared/ui/Tooltip";
import {
  ANNOTATION_COLORS,
  ANNOTATION_SWATCH,
  annotationColorLabel,
  type AnnotationColor,
  type AnnotationItem,
  type UnitKind,
} from "@/lib/reading-api";
import {
  coloursInView,
  effectiveColor,
  groupMarks,
  inView,
  marksToMarkdown,
  nextSort,
  sortLabel,
  tabCounts,
  visibleMarks,
  type AnnotationSort,
} from "@/lib/reading-mark-list";
import { AnnotationToolbar } from "./AnnotationToolbar";
import { MarkRow } from "./MarkRow";
import { toSelectable, useMarkSelection } from "./useMarkSelection";
import { unitLabel } from "./TextUnitView";

const AnnotationNoteEditor = dynamic(
  () => import("./AnnotationNoteEditor").then((module) => module.AnnotationNoteEditor),
  { ssr: false },
);

export interface AnnotationListProps {
  annotations: AnnotationItem[];
  unit: UnitKind;
  activeId: string | null;
  onSelect: (annotation: AnnotationItem) => void;
  onDelete: (annotation: AnnotationItem) => void | Promise<void>;
  /**
   * Rewrite the note on an existing mark. Absent means the host has no
   * update path, and the list then behaves as it always did.
   */
  onEditNote?: (annotation: AnnotationItem, note: string) => Promise<boolean>;
  /**
   * Recolour a mark or change what kind of mark it is. Absent leaves the
   * swatches and the kind toggle out, exactly as before.
   */
  onChangeMark?: (
    annotation: AnnotationItem,
    changes: { color?: string; kind?: AnnotationItem["kind"] },
  ) => Promise<boolean>;
}

/**
 * The marks made on this material, grouped by locator.
 *
 * Citations deliberately share the annotation store, selectors and source
 * positions. The tab is only a filtered view: it does not create a second
 * persistence model that could drift from the document's other marks.
 */
export function AnnotationList({
  annotations,
  unit,
  activeId,
  onSelect,
  onDelete,
  onEditNote,
  onChangeMark,
}: AnnotationListProps) {
  const { t } = useTranslation();
  const [view, setView] = useState<"annotations" | "citations">("annotations");
  const [query, setQuery] = useState("");
  // `null` means every colour.
  const [colorFilter, setColorFilter] = useState<string | null>(null);
  // Document order is the default: a reader who never touches the control sees
  // exactly what the list has always shown.
  const [sort, setSort] = useState<AnnotationSort>("document");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [savingNote, setSavingNote] = useState(false);
  const [noteError, setNoteError] = useState("");
  // A failed recolour has no editor to sit in, so it is reported at list level.
  const [listError, setListError] = useState("");
  const [copied, setCopied] = useState(false);
  const [busyMarks, setBusyMarks] = useState<Set<string>>(() => new Set());
  const busyMarksRef = useRef<Set<string>>(new Set());

  const usedColors = useMemo(
    () => coloursInView(annotations, view, ANNOTATION_COLORS),
    [annotations, view],
  );
  // A filter the current tab cannot satisfy does not apply; the reader's choice
  // is kept so switching back restores it.
  const appliedColor = effectiveColor(colorFilter, usedColors);

  const rows = useMemo(
    () => visibleMarks(annotations, { view, query, color: appliedColor }),
    [annotations, view, query, appliedColor],
  );
  const counts = useMemo(() => tabCounts(annotations), [annotations]);
  const groups = useMemo(() => groupMarks(rows, sort), [rows, sort]);

  const copyRows = async (targets: AnnotationItem[]): Promise<boolean> => {
    try {
      await navigator.clipboard.writeText(
        marksToMarkdown(targets, {
          unit: t(unitLabel(unit)),
          note: `${t("Note")}: `,
        }),
      );
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
      return true;
    } catch {
      setListError(t("Could not copy to the clipboard."));
      return false;
    }
  };

  const selection = useMarkSelection({
    rows: toSelectable(rows),
    onDelete,
    onCopy: copyRows,
  });


  /**
   * Recolour or re-kind one mark.
   *
   * A busy flag rather than per-row state: the list is short and one update at
   * a time keeps two rapid taps from racing each other's optimistic apply.
   */
  const applyMarkChange = async (
    annotation: AnnotationItem,
    changes: { color?: string; kind?: AnnotationItem["kind"] },
  ) => {
    const id = annotation.annotation_id;
    // Per-mark, not global: a second press on a *different* mark should not be
    // swallowed, and one row at a time is enough for the same mark.
    //
    // The guard reads the ref, not the state: two presses dispatched before
    // React re-renders would both see the same stale set.
    if (!onChangeMark || busyMarksRef.current.has(id)) return;
    busyMarksRef.current.add(id);
    setBusyMarks((current) => new Set(current).add(id));
    setListError("");
    const saved = await onChangeMark(annotation, changes);
    busyMarksRef.current.delete(id);
    setBusyMarks((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
    if (!saved) setListError(t("That annotation could not be saved."));
  };

  const recolour = (annotation: AnnotationItem, color: string) =>
    applyMarkChange(annotation, { color });

  const changeKind = (annotation: AnnotationItem, kind: AnnotationItem["kind"]) =>
    applyMarkChange(annotation, { kind });

  /**
   * Run the batch and report what happened.
   *
   * The hook returns how many deletes failed; the hosts roll those rows back
   * into the list, so without a notice the reader would see them reappear with
   * no explanation.
   */
  const runBatchDelete = async () => {
    setListError("");
    const total = selection.count;
    const failed = await selection.removeSelected();
    if (failed <= 0) return;
    setListError(
      failed === total
        ? t("That annotation could not be removed.")
        : t("Some annotations could not be removed."),
    );
  };

  const startEditing = (annotation: AnnotationItem) => {
    setEditingId(annotation.annotation_id);
    setNoteError("");
  };

  const cancelEditing = () => {
    setEditingId(null);
    setNoteError("");
  };

  const saveNote = async (annotation: AnnotationItem, note: string) => {
    if (!onEditNote) return;
    setSavingNote(true);
    setNoteError("");
    const saved = await onEditNote(annotation, note);
    setSavingNote(false);
    // Keep the editor open with the draft intact when the write failed: the
    // reader's text is not something to throw away on a network blip.
    if (saved) setEditingId(null);
    else setNoteError(t("That annotation could not be saved."));
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        role="tablist"
        aria-label={t("Saved reading marks")}
        className="grid shrink-0 grid-cols-2 gap-1 border-b border-[var(--border)] p-2"
      >
        <ViewTab
          active={view === "annotations"}
          icon={Highlighter}
          label={t("Annotations")}
          count={counts.annotations}
          onClick={() => setView("annotations")}
        />
        <ViewTab
          active={view === "citations"}
          icon={Bookmark}
          label={t("Citations")}
          count={counts.citations}
          onClick={() => setView("citations")}
        />
      </div>

      <AnnotationToolbar
        showSearch={Boolean(onEditNote)}
        query={query}
        sort={sort}
        colours={usedColors}
        appliedColor={appliedColor}
        selectionSelecting={selection.selecting}
        onQuery={setQuery}
        onCycleSort={() => setSort((current) => nextSort(current))}
        onToggleColor={setColorFilter}
        onStartSelection={selection.start}
        onStopSelection={selection.stop}
      />

      {selection.selecting && (
        <div className="mx-2.5 mt-2 flex shrink-0 items-center justify-between gap-2 rounded-md border border-[var(--border)] bg-[var(--muted)] px-2 py-1">
          <span className="text-[11px] text-[var(--muted-foreground)]">
            {selection.count > 0
              ? t("{{count}} selected", { count: selection.count })
              : t("Select annotations")}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => selection.toggleAll()}
              className="rounded px-1.5 py-0.5 text-[10.5px] text-[var(--muted-foreground)] hover:bg-[var(--background)]"
            >
              {selection.allSelected ? t("Clear selection") : t("Select all")}
            </button>
            <button
              type="button"
              disabled={selection.count === 0}
              data-testid="annotation-bulk-copy"
              onClick={() => void selection.copySelected()}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] text-[var(--muted-foreground)] hover:bg-[var(--background)] disabled:opacity-40"
            >
              <Copy size={10} aria-hidden />
              {copied ? t("Copied") : t("Copy")}
            </button>
            <button
              type="button"
              disabled={selection.count === 0}
              data-testid="annotation-bulk-delete"
              onClick={() => void runBatchDelete()}
              className="inline-flex items-center gap-1 rounded bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] px-1.5 py-0.5 text-[10.5px] font-medium text-[var(--destructive)] disabled:opacity-40"
            >
              <Trash2 size={10} aria-hidden />
              {t("Delete")}
            </button>
          </div>
        </div>
      )}

      {listError && (
        <p
          role="alert"
          className="mx-2.5 mt-2 rounded-md border border-[color-mix(in_srgb,var(--destructive)_30%,transparent)] bg-[color-mix(in_srgb,var(--destructive)_8%,transparent)] px-2 py-1 text-[11px] text-[var(--destructive)]"
        >
          {listError}
        </p>
      )}

      {!rows.length ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <Sparkles size={18} className="text-[color-mix(in_srgb,var(--muted-foreground)_60%,transparent)]" />
          <p className="text-[12px] font-medium text-[var(--foreground)]">
            {query.trim()
              ? t("No matching annotations")
              : t(
                  view === "citations"
                    ? "No citations yet"
                    : "No annotations yet",
                )}
          </p>
          <p className="max-w-[220px] text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            {query.trim()
              ? t("Try a different word, or clear the search.")
              : t(
                  view === "citations"
                    ? "Select text in the document to save a citation."
                    : "Select text in the document to highlight it or attach a note.",
                )}
          </p>
        </div>
      ) : (
        <div className="dt-reader-scroll min-h-0 flex-1 overflow-y-auto px-2.5 py-2">
          {groups.map((group) => (
            <section key={group.key} className="mb-3 last:mb-1">
              {sort === "document" && (
                // A time order has no page grouping to announce; a heading
                // would claim one that is not there.
                <h4 className="sticky top-0 z-10 mb-1 bg-[color-mix(in_srgb,var(--background)_95%,transparent)] px-1 py-1 font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--muted-foreground)] backdrop-blur">
                  {t(unitLabel(unit))} {group.locator}
                </h4>
              )}
              <ul className="space-y-1">
                {group.rows.map((annotation) => (
                  <MarkRow
                    key={annotation.annotation_id}
                    annotation={annotation}
                    active={annotation.annotation_id === activeId}
                    selecting={selection.selecting}
                    selected={selection.selected.has(annotation.annotation_id)}
                    editing={editingId === annotation.annotation_id}
                    savingNote={savingNote}
                    noteError={noteError}
                    busy={busyMarks.has(annotation.annotation_id)}
                    canEdit={Boolean(onEditNote)}
                    canChange={Boolean(onChangeMark)}
                    onSelect={onSelect}
                    onToggle={selection.toggle}
                    onDelete={onDelete}
                    onStartEditing={startEditing}
                    onCancelEditing={cancelEditing}
                    onSaveNote={saveNote}
                    onRecolour={recolour}
                    onChangeKind={changeKind}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function ViewTab({
  active,
  icon: Icon,
  label,
  count,
  onClick,
}: {
  active: boolean;
  icon: typeof Highlighter;
  label: string;
  /** How many rows this view holds; omitted when there is nothing to say. */
  count?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`inline-flex min-w-0 items-center justify-center gap-1 rounded-lg px-2 py-1.5 text-[11px] font-medium transition ${
        active
          ? "bg-[var(--muted)] text-[var(--foreground)]"
          : "text-[var(--muted-foreground)] hover:bg-[color-mix(in_srgb,var(--muted)_60%,transparent)] hover:text-[var(--foreground)]"
      }`}
    >
      <Icon size={12} />
      <span className="truncate">{label}</span>
      {count !== undefined && count > 0 && (
        <span className="shrink-0 rounded-full bg-[color-mix(in_srgb,currentColor_12%,transparent)] px-1 text-[9.5px] tabular-nums">
          {count}
        </span>
      )}
    </button>
  );
}
