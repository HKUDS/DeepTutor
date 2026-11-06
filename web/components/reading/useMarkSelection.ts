"use client";

import { useCallback, useRef, useState } from "react";

import type { AnnotationItem } from "@/lib/reading-api";

/** A row plus the identity the selection needs. */
export interface SelectableMark {
  id: string;
  mark: AnnotationItem;
}

/**
 * Opt-in multi-select and the batch actions over it.
 *
 * Selection is off until asked for: a row's first job is to jump to the mark,
 * and a checkbox on every row would demote that. Kept apart from the list
 * itself so the component that draws rows does not also own batch semantics.
 */
export function useMarkSelection({
  rows,
  onDelete,
  onCopy,
}: {
  /** The rows currently visible, i.e. what "select all" means. */
  rows: SelectableMark[];
  onDelete: (annotation: AnnotationItem) => void | Promise<void>;
  onCopy: (rows: AnnotationItem[]) => Promise<boolean>;
}) {
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  // Two presses dispatched before React re-renders both read the same state
  // closure, so the guard has to read a ref that updates synchronously.
  const busyRef = useRef(false);

  const start = useCallback(() => {
    setSelecting(true);
    setSelected(new Set());
  }, []);

  const stop = useCallback(() => {
    setSelecting(false);
    setSelected(new Set());
  }, []);

  const toggle = useCallback((id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelected((current) =>
      current.size === rows.length ? new Set() : new Set(rows.map((row) => row.id)),
    );
  }, [rows]);

  /**
   * Remove every selected mark, one at a time.
   *
   * The API deletes one row per request, so this walks the selection and waits
   * for each to settle before starting the next — the host's delete starts the
   * request and returns, so a bare loop would fire them all at once and a
   * failure in the middle would look identical to success.
   *
   * Returns how many failed, so the caller can say whether the batch failed
   * wholly or partly; `-1` means there was nothing to do.
   */
  const removeSelected = useCallback(async (): Promise<number> => {
    if (selected.size === 0 || busyRef.current) return -1;
    const targets = rows.filter((row) => selected.has(row.id));
    stop();
    busyRef.current = true;
    setBusy(true);
    let failed = 0;
    try {
      for (const row of targets) {
        try {
          await onDelete(row.mark);
        } catch {
          failed += 1;
        }
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
    return failed;
  }, [onDelete, rows, selected, stop]);

  /** Copy the selection; `false` means the clipboard refused. */
  const copySelected = useCallback(async (): Promise<boolean> => {
    if (selected.size === 0) return false;
    const targets = rows.filter((row) => selected.has(row.id)).map((row) => row.mark);
    return onCopy(targets);
  }, [onCopy, rows, selected]);

  return {
    selecting,
    selected,
    busy,
    start,
    stop,
    toggle,
    toggleAll,
    removeSelected,
    copySelected,
    count: selected.size,
    allSelected: rows.length > 0 && selected.size === rows.length,
  };
}

/** Wrap the visible marks for `useMarkSelection`. */
export function toSelectable(rows: AnnotationItem[]): SelectableMark[] {
  return rows.map((mark) => ({ id: mark.annotation_id, mark }));
}
