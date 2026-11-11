import type { AnnotationDraft, AnnotationItem } from "@/lib/reading-api";

/**
 * Build the update for an existing mark from the fields the reader changed.
 *
 * Shared by every surface that lets a mark be edited — the pane's own list and
 * the workspace's contents navigator both mount one — so the rule lives in one
 * place rather than being restated per host.
 *
 * Only the changed fields move. `quote`, `rects`, `selectors` and `created_at`
 * are what the mark *is*: re-sending different ones would move the highlight
 * off the words it belongs to, or re-anchor it against text nobody selected.
 */
export function buildMarkUpdate(
  annotation: AnnotationItem,
  changes: { note?: string; color?: string; kind?: AnnotationItem["kind"] },
): { draft: AnnotationDraft; optimistic: AnnotationItem } | null {
  // Resolve each field once; `undefined` means the caller did not touch it.
  const note = changes.note === undefined ? annotation.note : changes.note.trim();
  const color = changes.color ?? annotation.color;
  const kind = changes.kind ?? annotation.kind;

  // Nothing actually changed: report null so the caller can skip the round
  // trip instead of bumping `updated_at` for a no-op. An emptied note counts
  // as no change too — that is a delete in disguise, and deleting is its own
  // explicit action.
  if (
    (note === annotation.note || note === "") &&
    color === annotation.color &&
    kind === annotation.kind
  ) {
    return null;
  }

  const next: AnnotationItem = {
    ...annotation,
    note,
    color,
    kind,
    updated_at: Date.now() / 1000,
  };

  return {
    draft: {
      annotation_id: annotation.annotation_id,
      locator: annotation.locator,
      kind: next.kind,
      color: next.color,
      quote: annotation.quote,
      note: next.note,
      rects: annotation.rects,
      source_anchor: annotation.source_anchor,
      selectors: annotation.selectors ?? [],
      // The copy this edit was built from, so a second tab cannot silently
      // overwrite it: the store answers 409 when the row has moved on.
      expected_updated_at: annotation.updated_at,
    },
    optimistic: next,
  };
}
