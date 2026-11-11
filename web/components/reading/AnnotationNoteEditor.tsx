"use client";

import { Pencil, StickyNote, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * Inline editor for the note attached to one saved mark.
 *
 * The document reader could add a note with a mark and delete the whole mark,
 * but not come back later and change what the note says — the backend has
 * always supported it (`PUT /annotations` updates when `annotation_id` is
 * present, and the media reader already uses that path), so the missing piece
 * was only this affordance.
 *
 * Editing rather than re-marking matters: a mark is anchored to a quote and to
 * normalised rects, so re-creating it would move the highlight and lose the
 * `created_at` the list sorts by.
 */
export function AnnotationNoteEditor({
  initialNote,
  saving,
  error,
  onCancel,
  onSave,
}: {
  initialNote: string;
  saving: boolean;
  /** Message from a failed save; the draft is kept so nothing is lost. */
  error: string;
  onCancel: () => void;
  onSave: (note: string) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(initialNote);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Focus lands in the field with the caret at the end: the reader pressed
  // "edit", not "append", and starting at the end is where the next thought
  // usually goes.
  useEffect(() => {
    const field = textareaRef.current;
    if (!field) return;
    field.focus();
    const end = field.value.length;
    field.setSelectionRange(end, end);
  }, []);

  const trimmed = draft.trim();

  return (
    <div className="mt-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] p-2">
      <label className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
        <Pencil size={10} aria-hidden />
        {t("Edit note")}
      </label>
      <textarea
        ref={textareaRef}
        value={draft}
        data-testid="annotation-note-input"
        aria-label={t("Edit note")}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          // Escape abandons the edit; the caller keeps the saved note intact.
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            onCancel();
            return;
          }
          // ⌘/Ctrl+Enter saves, matching the composer and the note dialogs.
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            if (trimmed && !saving) onSave(trimmed);
          }
        }}
        rows={3}
        className="mt-1.5 w-full resize-y rounded-md border border-[var(--border)] bg-[var(--background)] p-1.5 text-[11.5px] leading-relaxed text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
      />
      {error && (
        <p role="alert" className="mt-1.5 text-[11px] text-[var(--destructive)]">
          {error}
        </p>
      )}
      <div className="mt-1.5 flex items-center justify-end gap-1">
        <button
          type="button"
          onClick={onCancel}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
        >
          <X size={11} aria-hidden />
          {t("Cancel")}
        </button>
        <button
          type="button"
          onClick={() => onSave(trimmed)}
          // An emptied note is a delete in disguise; removing the whole mark is
          // the explicit action for that, so this stays disabled instead.
          disabled={!trimmed || saving}
          data-testid="annotation-note-save"
          className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-2 py-1 text-[10.5px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
        >
          <StickyNote size={11} aria-hidden />
          {t("Save note")}
        </button>
      </div>
    </div>
  );
}
