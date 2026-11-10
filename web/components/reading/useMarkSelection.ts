"use client";

import { useCallback, useMemo, useRef, useState } from "react";

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
  onDelete: (annotation: AnnotationItem) => void | Promise<void | boolean>;
  onCopy: (rows: AnnotationItem[]) => Promise<boolean>;
}) {
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  // Selection is kept in step with what is on screen. A search or colour filter
  // can hide a row that is still selected; leaving it in the set made the
  // batch delete fewer rows than the count promised, with no notice, because
  // the batch only walks visible rows. Pruning here means `count` and "select
  // all" always describe the same set the actions will touch.
  const visibleIds = useMemo(
    () => new Set(rows.map((row) => row.id)),
    [rows],
  );
  const live = useMemo(
    () => new Set([...selected].filter((id) => visibleIds.has(id))),
    [selected, visibleIds],
  );
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
    setSelected((current) => {
      const already = new Set([...current].filter((id) => visibleIds.has(id)));
      return already.size === rows.length
        ? new Set()
        : new Set(rows.map((row) => row.id));
    });
  }, [rows, visibleIds]);

  /**
   * Remove every selected mark, one at a time.
   *
   * The API deletes one row per request, so this walks the selection and waits
   * for each to settle before starting the next — a bare loop would fire them
   * all at once and a failure in the middle would look identical to success.
   *
   * A host reports a failed delete by resolving `false` (the reader has
   * already rolled the row back and shown the notice) or by rejecting.
   *
   * Returns how many failed, so the caller can say whether the batch failed
   * wholly or partly; `-1` means there was nothing to do.
   */
  const removeSelected = useCallback(async (): Promise<number> => {
    if (live.size === 0 || busyRef.current) return -1;
    const targets = rows.filter((row) => live.has(row.id));
    stop();
    busyRef.current = true;
    setBusy(true);
    let failed = 0;
    try {
      for (const row of targets) {
        try {
          if ((await onDelete(row.mark)) === false) failed += 1;
        } catch {
          failed += 1;
        }
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
    return failed;
  }, [onDelete, rows, live, stop]);

  /** Copy the selection; `false` means the clipboard refused. */
  const copySelected = useCallback(async (): Promise<boolean> => {
    if (live.size === 0) return false;
    const targets = rows.filter((row) => live.has(row.id)).map((row) => row.mark);
    return onCopy(targets);
  }, [onCopy, rows, live]);

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
    count: live.size,
    allSelected: rows.length > 0 && live.size === rows.length,
  };
}

/** Wrap the visible marks for `useMarkSelection`. */
export function toSelectable(rows: AnnotationItem[]): SelectableMark[] {
  return rows.map((mark) => ({ id: mark.annotation_id, mark }));
}
