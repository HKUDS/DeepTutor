"use client";

import dynamic from "next/dynamic";
import { MarkBadges } from "./MarkBadges";
import { MarkPalette } from "./MarkPalette";
import { Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/shared/ui/Tooltip";
import {
  ANNOTATION_SWATCH,
  type AnnotationColor,
  type AnnotationItem,
} from "@/lib/reading-api";

const AnnotationNoteEditor = dynamic(
  () => import("./AnnotationNoteEditor").then((module) => module.AnnotationNoteEditor),
  { ssr: false },
);

/**
 * One saved mark, drawn in the list.
 *
 * Split out of the list itself: the list decides what to show and in what
 * order, this decides what a row looks like and how it responds. A row owns
 * seven interactions (jump, select, edit, recolour, re-kind, delete, checkbox),
 * which is more than belongs in the middle of a 600-line component.
 */
export function MarkRow({
  annotation,
  active,
  selecting,
  selected,
  editing,
  savingNote,
  noteError,
  busy,
  canEdit,
  canChange,
  onSelect,
  onToggle,
  onDelete,
  onStartEditing,
  onCancelEditing,
  onSaveNote,
  onRecolour,
  onChangeKind,
}: {
  annotation: AnnotationItem;
  active: boolean;
  selecting: boolean;
  selected: boolean;
  editing: boolean;
  savingNote: boolean;
  noteError: string;
  busy: boolean;
  canEdit: boolean;
  canChange: boolean;
  onSelect: (annotation: AnnotationItem) => void;
  onToggle: (id: string) => void;
  onDelete: (annotation: AnnotationItem) => void;
  onStartEditing: (annotation: AnnotationItem) => void;
  onCancelEditing: () => void;
  onSaveNote: (annotation: AnnotationItem, note: string) => Promise<void>;
  onRecolour: (annotation: AnnotationItem, color: string) => void;
  onChangeKind: (annotation: AnnotationItem, kind: AnnotationItem["kind"]) => void;
}) {
  const { t } = useTranslation();
  return (
    <li>
  <div
    role="button"
    tabIndex={0}
    onClick={() => (selecting ? onToggle(annotation.annotation_id) : onSelect(annotation))}
    onKeyDown={(event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onSelect(annotation);
      }
    }}
    className={`group/anno relative w-full cursor-pointer rounded-lg border px-2.5 py-2 text-left transition ${
      active
        ? "border-[var(--ring)] bg-[color-mix(in_srgb,var(--muted)_60%,transparent)]"
        : "border-transparent hover:border-[var(--border)] hover:bg-[color-mix(in_srgb,var(--muted)_40%,transparent)]"
    }`}
  >
    <span
      aria-hidden
      className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full"
      style={{
        background:
          ANNOTATION_SWATCH[
            annotation.color as AnnotationColor
          ] ?? ANNOTATION_SWATCH.yellow,
      }}
    />
    {selecting && (
      <input
        type="checkbox"
        checked={selected}
        aria-label={`${t("Select annotations")}: ${annotation.quote || annotation.note || annotation.annotation_id}`}
        onClick={(event) => event.stopPropagation()}
        onChange={() => onToggle(annotation.annotation_id)}
        className="absolute right-2 top-2 h-3.5 w-3.5"
      />
    )}
    {annotation.quote && (
      <p className="line-clamp-3 pl-1.5 text-[12px] leading-[1.55] text-[var(--foreground)]">
        {annotation.quote}
      </p>
    )}
    {annotation.note && !editing && (
      <p className="mt-1 line-clamp-3 pl-1.5 text-[11px] leading-[1.5] text-[var(--muted-foreground)]">
        {annotation.note}
      </p>
    )}
    {editing && (
      // Clicking inside the editor must not re-open the
      // mark's jump; the row itself is the select target.
      <div
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
        role="presentation"
      >
        <AnnotationNoteEditor
          initialNote={annotation.note}
          saving={savingNote}
          error={noteError}
          onCancel={onCancelEditing}
          onSave={(note) => void onSaveNote(annotation, note)}
        />
      </div>
    )}
    <MarkBadges annotation={annotation} />
    {canChange && !editing && (
      <MarkPalette
        annotation={annotation}
        busy={busy}
        onRecolour={onRecolour}
        onChangeKind={onChangeKind}
      />
    )}

    {!selecting && <span className="absolute right-1.5 top-1.5 flex items-center gap-0.5 opacity-0 transition focus-within:opacity-100 group-hover/anno:opacity-100">
      {canEdit && !editing && (
        <Tooltip label={t("Edit note")}>
          <button
            type="button"
            aria-label={t("Edit note")}
            onClick={(event) => {
              event.stopPropagation();
              onStartEditing(annotation);
            }}
            className="inline-flex h-6 w-6 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <Pencil size={12} />
          </button>
        </Tooltip>
      )}
      <Tooltip label={t("Delete annotation")}>
        <button
          type="button"
          aria-label={t("Delete annotation")}
          onClick={(event) => {
            event.stopPropagation();
            onDelete(annotation);
          }}
          className="inline-flex h-6 w-6 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[color-mix(in_srgb,var(--destructive)_10%,transparent)] hover:text-[var(--destructive)]"
        >
          <Trash2 size={12} />
        </button>
      </Tooltip>
    </span>}
  </div>
    </li>
  );
}