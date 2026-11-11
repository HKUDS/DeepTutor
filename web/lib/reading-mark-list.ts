import type { AnnotationItem } from "@/lib/reading-api";

/**
 * Which marks the list shows, and in what order.
 *
 * Pure: given the saved marks and the reader's choices, return the rows to
 * draw. Keeping this out of the component means the filter and the order can
 * be reasoned about — and tested — without a DOM, and the component is left
 * with layout rather than data selection.
 */

export type AnnotationView = "annotations" | "citations";
export type AnnotationSort = "document" | "newest" | "oldest";

/** How the saved marks are ordered in the list. */
export const SORT_ORDER: AnnotationSort[] = ["document", "newest", "oldest"];

export function nextSort(current: AnnotationSort): AnnotationSort {
  const index = SORT_ORDER.indexOf(current);
  return SORT_ORDER[(index + 1) % SORT_ORDER.length];
}

/** Literal keys so i18n can find them. */
export function sortLabel(sort: AnnotationSort): string {
  switch (sort) {
    case "newest":
      return "Newest first";
    case "oldest":
      return "Oldest first";
    default:
      return "Document order";
  }
}

/** Whether a mark belongs in the tab currently in view. */
export function inView(annotation: AnnotationItem, view: AnnotationView): boolean {
  return view === "citations"
    ? annotation.kind === "citation"
    : annotation.kind !== "citation";
}

/** The colours present in one tab, in palette order. */
export function coloursInView<T extends string>(
  annotations: AnnotationItem[],
  view: AnnotationView,
  palette: readonly T[],
): T[] {
  const seen = new Set<string>();
  for (const annotation of annotations) {
    if (inView(annotation, view)) seen.add(annotation.color);
  }
  return palette.filter((color) => seen.has(color));
}

/**
 * How many rows each tab holds.
 *
 * Independent of the search and the colour filter: the badge describes the
 * collection, not the current view of it.
 */
export function tabCounts(annotations: AnnotationItem[]): {
  annotations: number;
  citations: number;
} {
  let annotationsCount = 0;
  let citationsCount = 0;
  for (const annotation of annotations) {
    if (annotation.kind === "citation") citationsCount += 1;
    else annotationsCount += 1;
  }
  return { annotations: annotationsCount, citations: citationsCount };
}

/** The rows in the tab, narrowed by the search and the colour filter. */
export function visibleMarks(
  annotations: AnnotationItem[],
  options: {
    view: AnnotationView;
    query: string;
    /** Already resolved against the colours the tab can offer. */
    color: string | null;
  },
): AnnotationItem[] {
  // NFC so a composed and a decomposed accent are the same letter to the
  // search: "é" typed as U+00E9 must match text stored as "e" + U+0301.
  const needle = options.query.trim().normalize("NFC").toLowerCase();
  return annotations.filter((annotation) => {
    if (!inView(annotation, options.view)) return false;
    if (options.color !== null && annotation.color !== options.color) return false;
    if (!needle) return true;
    // A reader looking for "that note about latency" should not have to
    // remember which page it was on.
    return (
      annotation.quote.normalize("NFC").toLowerCase().includes(needle) ||
      annotation.note.normalize("NFC").toLowerCase().includes(needle)
    );
  });
}

/** One page-worth of rows, or one row in a time order. */
export interface MarkGroup {
  /** Stable React key: the page in document order, the mark in a time order. */
  key: string;
  /** The page this group belongs to, for the heading. */
  locator: number;
  rows: AnnotationItem[];
}

/**
 * Group the rows for drawing.
 *
 * Document order keeps the page headings, because that is the shape that
 * matches the document being read. The time orders are flat — a reader asking
 * "what did I just write" does not want page headings interrupting a list that
 * is no longer grouped by page — and each row is its own group.
 */
export function groupMarks(rows: AnnotationItem[], sort: AnnotationSort): MarkGroup[] {
  if (sort !== "document") {
    const ordered = [...rows].sort((a, b) =>
      sort === "newest" ? b.created_at - a.created_at : a.created_at - b.created_at,
    );
    // The key is the mark, not the page: two marks on one page would otherwise
    // collide and React would reuse the wrong row's DOM.
    return ordered.map((annotation) => ({
      key: `mark-${annotation.annotation_id}`,
      locator: annotation.locator,
      rows: [annotation],
    }));
  }
  const byLocator = new Map<number, AnnotationItem[]>();
  for (const annotation of rows) {
    const bucket = byLocator.get(annotation.locator) ?? [];
    bucket.push(annotation);
    byLocator.set(annotation.locator, bucket);
  }
  return [...byLocator.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([locator, groupRows]) => ({
      key: `locator-${locator}`,
      locator,
      rows: groupRows,
    }));
}

/**
 * The filter the current tab can actually honour.
 *
 * A colour chosen in one tab may not exist in the other; applying it there
 * would empty the list and blame the reader's search. The choice is kept, not
 * cleared, so switching back restores it.
 */
export function effectiveColor(
  chosen: string | null,
  offered: string[],
): string | null {
  return chosen !== null && offered.includes(chosen) ? chosen : null;
}

/**
 * Render marks as Markdown a reader can paste somewhere else.
 *
 * Quote first, then the note underneath, then the page: that is the order a
 * person reading their own notes back wants, and it is what the Markdown
 * export already produces.
 */
export function marksToMarkdown(
  rows: AnnotationItem[],
  labels: { unit: string; note: string },
): string {
  return rows
    .map((row) => {
      const quote = row.quote.trim();
      const note = row.note.trim();
      const lines = [`**${labels.unit} ${row.locator}**`];
      if (quote) lines.push(`> ${quote}`);
      if (note) lines.push(`${labels.note}${note}`);
      return lines.join("\n");
    })
    .join("\n\n");
}
