"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Pencil, StickyNote, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { Block } from "@/lib/book-types";

export interface UserNoteBlockProps {
  block: Block;
  /** Omit to render read-only (e.g. in a preview context). */
  onSave?: (body: string) => Promise<void> | void;
  /** Start in edit mode — used when the note was just inserted. */
  autoEdit?: boolean;
}

/**
 * The reader's own margin note.
 *
 * Previously this rendered the invitation "start writing your own annotation"
 * with nowhere to write: the block type, the payload field and the insert
 * action all existed, but no editor was ever wired up.
 */
export default function UserNoteBlock({
  block,
  onSave,
  autoEdit = false,
}: UserNoteBlockProps) {
  const { t } = useTranslation();
  const body = String(block.payload?.body || "");
  const editable = !!onSave;

  const [editing, setEditing] = useState(autoEdit && editable);
  const [draft, setDraft] = useState(body);
  const [saving, setSaving] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Re-sync when the block changes underneath us (a refresh, another device).
  useEffect(() => {
    if (!editing) setDraft(body);
  }, [body, editing]);

  useEffect(() => {
    if (!editing) return;
    const node = textareaRef.current;
    if (!node) return;
    node.focus();
    node.setSelectionRange(node.value.length, node.value.length);
  }, [editing]);

  const commit = async () => {
    if (!onSave || saving) return;
    setSaving(true);
    try {
      await onSave(draft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const cancel = () => {
    setDraft(body);
    setEditing(false);
  };

  return (
    <aside className="group/note flex gap-3 border-l-[3px] border-dashed border-[var(--primary)]/50 bg-[var(--primary)]/[0.04] py-2 pl-4 pr-3">
      <StickyNote className="mt-[3px] h-4 w-4 shrink-0 text-[var(--primary)]" />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--primary)]">
            {t("Your note")}
          </div>
          {editable && !editing && (
            <button
              type="button"
              onClick={() => setEditing(true)}
              title={t("Edit note")}
              className="inline-flex h-6 w-6 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-0 transition-opacity hover:bg-[var(--background)] hover:text-[var(--foreground)] group-hover/note:opacity-100"
            >
              <Pencil className="h-3 w-3" />
            </button>
          )}
        </div>

        {editing ? (
          <div className="space-y-1.5">
            <textarea
              ref={textareaRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  cancel();
                } else if (
                  event.key === "Enter" &&
                  (event.metaKey || event.ctrlKey)
                ) {
                  event.preventDefault();
                  void commit();
                }
              }}
              rows={4}
              placeholder={t("Markdown supported. ⌘/Ctrl + Enter to save.")}
              className="w-full resize-y rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-sm text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/60 focus:border-[var(--primary)]/50"
            />
            <div className="flex items-center justify-end gap-1.5">
              <button
                type="button"
                onClick={cancel}
                disabled={saving}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[11px] font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-50"
              >
                <X className="h-3 w-3" />
                {t("Cancel")}
              </button>
              <button
                type="button"
                onClick={() => void commit()}
                disabled={saving}
                className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-2 py-0.5 text-[11px] font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
              >
                {saving ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Check className="h-3 w-3" />
                )}
                {t("Save")}
              </button>
            </div>
          </div>
        ) : body ? (
          <MarkdownRenderer content={body} variant="compact" />
        ) : (
          <button
            type="button"
            onClick={() => editable && setEditing(true)}
            disabled={!editable}
            className="text-left text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:cursor-default disabled:hover:text-[var(--muted-foreground)]"
          >
            {editable
              ? t("Empty note — click to start writing your own annotation.")
              : t("Empty note.")}
          </button>
        )}
      </div>
    </aside>
  );
}
