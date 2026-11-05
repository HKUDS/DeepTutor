import { describe, expect, it } from "vitest";
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
} from "@/lib/reading-mark-list";
import type { AnnotationItem } from "@/lib/reading-api";

function mark(overrides: Partial<AnnotationItem> = {}): AnnotationItem {
  return {
    annotation_id: "a1",
    locator: 1,
    kind: "highlight",
    color: "yellow",
    quote: "quote",
    note: "",
    rects: [],
    source_anchor: "",
    author: "user",
    created_at: 1,
    updated_at: 1,
    ...overrides,
  } as AnnotationItem;
}

/**
 * The list's data selection, without a DOM.
 *
 * Its node:test twin lives in `reading-mark-list.test.ts`; this spec exists so
 * the vitest-driven coverage and mutation runs reach the same assertions.
 */
describe("which rows a tab shows", () => {
  it("separates citations from the other marks", () => {
    expect(inView(mark({ kind: "highlight" }), "annotations")).toBe(true);
    expect(inView(mark({ kind: "citation" }), "annotations")).toBe(false);
    expect(inView(mark({ kind: "citation" }), "citations")).toBe(true);
    expect(inView(mark({ kind: "note" }), "citations")).toBe(false);
  });

  it("counts each tab independently of the filters", () => {
    const rows = [
      mark({ kind: "highlight" }),
      mark({ kind: "note" }),
      mark({ kind: "citation" }),
    ];
    expect(tabCounts(rows)).toEqual({ annotations: 2, citations: 1 });
  });
});

describe("narrowing the rows", () => {
  const rows = [
    mark({ annotation_id: "y1", locator: 1, color: "yellow", quote: "latency budget" }),
    mark({ annotation_id: "g1", locator: 2, color: "green", quote: "cache", note: "TTL" }),
    mark({ annotation_id: "c1", locator: 3, kind: "citation", color: "blue", quote: "throughput" }),
  ];

  it("searches quotes and notes", () => {
    expect(
      visibleMarks(rows, { view: "annotations", query: "cache", color: null }).map(
        (row) => row.annotation_id,
      ),
    ).toEqual(["g1"]);
    expect(
      visibleMarks(rows, { view: "annotations", query: "TTL", color: null }).map(
        (row) => row.annotation_id,
      ),
    ).toEqual(["g1"]);
  });

  it("combines the search with the colour instead of replacing it", () => {
    const both = visibleMarks(rows, {
      view: "annotations",
      query: "e",
      color: "yellow",
    });
    expect(both.map((row) => row.annotation_id)).toEqual(["y1"]);
  });

  it("does not leak the other tab's rows", () => {
    expect(
      visibleMarks(rows, { view: "citations", query: "throughput", color: null }).map(
        (row) => row.annotation_id,
      ),
    ).toEqual(["c1"]);
  });
});

describe("the palette a tab can offer", () => {
  const rows = [
    mark({ color: "yellow" }),
    mark({ color: "green" }),
    mark({ kind: "citation", color: "blue" }),
  ];
  const palette = ["yellow", "green", "blue", "pink", "purple"] as const;

  it("counts only the colours in view", () => {
    expect(coloursInView(rows, "annotations", palette)).toEqual(["yellow", "green"]);
    expect(coloursInView(rows, "citations", palette)).toEqual(["blue"]);
  });

  it("keeps a colour the tab cannot honour from applying", () => {
    expect(effectiveColor("yellow", ["blue"])).toBeNull();
    expect(effectiveColor("yellow", ["yellow", "green"])).toBe("yellow");
    expect(effectiveColor(null, ["yellow"])).toBeNull();
  });
});

describe("grouping for drawing", () => {
  const rows = [
    mark({ annotation_id: "b", locator: 5, created_at: 20 }),
    mark({ annotation_id: "a", locator: 2, created_at: 10 }),
    mark({ annotation_id: "c", locator: 9, created_at: 30 }),
  ];

  it("groups by page in document order", () => {
    const groups = groupMarks(rows, "document");
    expect(groups.map((group) => group.locator)).toEqual([2, 5, 9]);
    expect(groups.every((group) => group.key.startsWith("locator-"))).toBe(true);
  });

  it("makes one group per mark in a time order", () => {
    const groups = groupMarks(rows, "newest");
    expect(groups.map((group) => group.rows[0].annotation_id)).toEqual(["c", "b", "a"]);
    expect(groups.every((group) => group.key.startsWith("mark-"))).toBe(true);
  });

  it("gives two marks on one page distinct keys in a time order", () => {
    const groups = groupMarks(
      [
        mark({ annotation_id: "x", locator: 3, created_at: 1 }),
        mark({ annotation_id: "y", locator: 3, created_at: 2 }),
      ],
      "newest",
    );
    expect(new Set(groups.map((group) => group.key)).size).toBe(2);
  });

  it("orders oldest first when asked", () => {
    const groups = groupMarks(rows, "oldest");
    expect(groups.map((group) => group.rows[0].annotation_id)).toEqual(["a", "b", "c"]);
  });
});

describe("cycling the order", () => {
  it("goes document → newest → oldest → document", () => {
    expect(nextSort("document")).toBe("newest");
    expect(nextSort("newest")).toBe("oldest");
    expect(nextSort("oldest")).toBe("document");
  });

  it("names each order with a literal key", () => {
    expect(sortLabel("document")).toBe("Document order");
    expect(sortLabel("newest")).toBe("Newest first");
    expect(sortLabel("oldest")).toBe("Oldest first");
  });
});

describe("marks as Markdown", () => {
  it("puts the page, the quote and the note in reading order", () => {
    const text = marksToMarkdown(
      [mark({ locator: 4, quote: "the latency budget", note: "worth re-reading" })],
      { unit: "Page", note: "Note: " },
    );
    expect(text).toContain("**Page 4**");
    expect(text).toContain("> the latency budget");
    expect(text).toContain("Note: worth re-reading");
  });

  it("omits an absent note instead of printing an empty label", () => {
    const text = marksToMarkdown([mark({ quote: "only a quote" })], {
      unit: "Page",
      note: "Note: ",
    });
    expect(text).not.toContain("Note:");
  });

  it("separates several marks with a blank line", () => {
    const text = marksToMarkdown(
      [
        mark({ annotation_id: "a", locator: 1, quote: "one" }),
        mark({ annotation_id: "b", locator: 2, quote: "two" }),
      ],
      { unit: "Page", note: "Note: " },
    );
    expect(text.split("\n\n")).toHaveLength(2);
  });
});
