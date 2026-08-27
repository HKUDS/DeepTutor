"use client";

import { Check, Pencil, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Translate } from "./format";

/**
 * The path's name, and the only place it can be changed.
 *
 * A path is named by the tutor when it is built, which makes that name a good
 * default and a poor final answer — it is the learner's course, so the learner
 * gets to say what it is called. Editing happens in place rather than through a
 * dialog: the title is one line, and a modal for one line reads as a bigger
 * commitment than renaming actually is.
 *
 * Submitting an empty name is allowed and meaningful — it hands the path back
 * to its derived name (the tutor's, or the first module's) instead of pinning
 * an empty string.
 *
 * Losing focus does NOT save. A rename is a deliberate act, and committing on
 * blur turns "clicked somewhere else" into a silent rename — while also racing
 * whatever focus the field was given when it opened. Blur only closes an
 * editor the learner never changed.
 */
export function PathTitle({
  name,
  onRename,
  tr,
}: {
  name: string;
  /** Resolves once the new name is committed; may reject. */
  onRename: (name: string) => Promise<void>;
  tr: Translate;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reopen on a different path (or after a rename lands) with that path's name,
  // never with whatever was half-typed for the previous one.
  useEffect(() => {
    if (!editing) setDraft(name);
  }, [name, editing]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const commit = async () => {
    if (saving) return;
    const next = draft.trim();
    if (next === name.trim()) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onRename(next);
      setEditing(false);
    } catch {
      // Keep the editor open with the text still in it — the alternative is
      // silently discarding what they typed.
    } finally {
      setSaving(false);
    }
  };

  const cancel = () => {
    setDraft(name);
    setEditing(false);
  };

  if (!editing) {
    return (
      <div className="flex min-w-0 items-center gap-1.5">
        <h2 className="truncate text-sm font-semibold text-[var(--foreground)]">
          {name}
        </h2>
        {/* Always present, like the reset/delete controls beside it. A
            hover-revealed affordance does not exist on a touch screen. */}
        <button
          onClick={() => setEditing(true)}
          title={tr("重命名", "Rename")}
          className="shrink-0 cursor-pointer rounded p-1 text-[var(--muted-foreground)]/60 transition-colors hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
        >
          <Pencil className="h-3 w-3" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <input
        ref={inputRef}
        value={draft}
        autoFocus
        disabled={saving}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") void commit();
          if (event.key === "Escape") cancel();
        }}
        onBlur={() => {
          if (draft.trim() === name.trim()) setEditing(false);
        }}
        maxLength={200}
        placeholder={tr("这条路叫什么？", "What is this path called?")}
        className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm text-[var(--foreground)] outline-none focus:border-[var(--primary)] disabled:opacity-60"
      />
      {/* mousedown, not click: blur fires first and would commit-then-cancel. */}
      <button
        onMouseDown={(event) => {
          event.preventDefault();
          void commit();
        }}
        title={tr("保存", "Save")}
        className="shrink-0 cursor-pointer rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
      >
        <Check className="h-3.5 w-3.5" />
      </button>
      <button
        onMouseDown={(event) => {
          event.preventDefault();
          cancel();
        }}
        title={tr("取消", "Cancel")}
        className="shrink-0 cursor-pointer rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
