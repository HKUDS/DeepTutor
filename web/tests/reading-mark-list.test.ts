import test from "node:test";
import assert from "node:assert/strict";
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
} from "../lib/reading-mark-list";
import type { AnnotationItem } from "../lib/reading-api";

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
 * These were inline in a 796-line component; extracting them is what makes
 * them testable this directly, and what keeps the component down to layout.
 */
test("which rows a tab shows", async (t) => {
  await t.test("separates citations from the other marks", () => {
    assert.equal(inView(mark({ kind: "highlight" }), "annotations"), true);
    assert.equal(inView(mark({ kind: "citation" }), "annotations"), false);
    assert.equal(inView(mark({ kind: "citation" }), "citations"), true);
    assert.equal(inView(mark({ kind: "note" }), "citations"), false);
  });

  await t.test("counts each tab independently of the filters", () => {
    const rows = [
      mark({ kind: "highlight" }),
      mark({ kind: "note" }),
      mark({ kind: "citation" }),
    ];
    assert.deepEqual(tabCounts(rows), { annotations: 2, citations: 1 });
  });
});

test("narrowing the rows", async (t) => {
  const rows = [
    mark({ annotation_id: "y1", locator: 1, color: "yellow", quote: "latency budget" }),
    mark({ annotation_id: "g1", locator: 2, color: "green", quote: "cache", note: "TTL" }),
    mark({ annotation_id: "c1", locator: 3, kind: "citation", color: "blue", quote: "throughput" }),
  ];

  await t.test("searches quotes and notes", () => {
    assert.deepEqual(
      visibleMarks(rows, { view: "annotations", query: "cache", color: null }).map(
        (row) => row.annotation_id,
      ),
      ["g1"],
    );
    // A match in the note counts too.
    assert.deepEqual(
      visibleMarks(rows, { view: "annotations", query: "TTL", color: null }).map(
        (row) => row.annotation_id,
      ),
      ["g1"],
    );
  });

  await t.test("combines the search with the colour instead of replacing it", () => {
    const both = visibleMarks(rows, {
      view: "annotations",
      query: "e",
      color: "yellow",
    });
    assert.deepEqual(both.map((row) => row.annotation_id), ["y1"]);
  });

  await t.test("does not leak the other tab's rows", () => {
    assert.deepEqual(
      visibleMarks(rows, { view: "citations", query: "throughput", color: null }).map(
        (row) => row.annotation_id,
      ),
      ["c1"],
    );
  });
});

test("the palette a tab can offer", async (t) => {
  const rows = [
    mark({ color: "yellow" }),
    mark({ color: "green" }),
    mark({ kind: "citation", color: "blue" }),
  ];
  const palette = ["yellow", "green", "blue", "pink", "purple"] as const;

  await t.test("counts only the colours in view", () => {
    assert.deepEqual(coloursInView(rows, "annotations", palette), ["yellow", "green"]);
    assert.deepEqual(coloursInView(rows, "citations", palette), ["blue"]);
  });

  await t.test("keeps a colour the tab cannot honour from applying", () => {
    // Choosing yellow in Annotations, then opening Citations (blue only):
    // applying it there would empty the list and blame the search.
    assert.equal(effectiveColor("yellow", ["blue"]), null);
    assert.equal(effectiveColor("yellow", ["yellow", "green"]), "yellow");
    assert.equal(effectiveColor(null, ["yellow"]), null);
  });
});

test("grouping for drawing", async (t) => {
  const rows = [
    mark({ annotation_id: "b", locator: 5, created_at: 20 }),
    mark({ annotation_id: "a", locator: 2, created_at: 10 }),
    mark({ annotation_id: "c", locator: 9, created_at: 30 }),
  ];

  await t.test("groups by page in document order", () => {
    const groups = groupMarks(rows, "document");
    assert.deepEqual(groups.map((group) => group.locator), [2, 5, 9]);
    assert.equal(groups.every((group) => group.key.startsWith("locator-")), true);
  });

  await t.test("makes one group per mark in a time order", () => {
    const groups = groupMarks(rows, "newest");
    assert.deepEqual(groups.map((group) => group.rows[0].annotation_id), ["c", "b", "a"]);
    // Keyed by the mark: two marks on one page must not collide.
    assert.equal(groups.every((group) => group.key.startsWith("mark-")), true);
  });

  await t.test("gives two marks on one page distinct keys in a time order", () => {
    const groups = groupMarks(
      [mark({ annotation_id: "x", locator: 3, created_at: 1 }),
       mark({ annotation_id: "y", locator: 3, created_at: 2 })],
      "newest",
    );
    assert.equal(new Set(groups.map((group) => group.key)).size, 2);
  });

  await t.test("orders oldest first when asked", () => {
    const groups = groupMarks(rows, "oldest");
    assert.deepEqual(groups.map((group) => group.rows[0].annotation_id), ["a", "b", "c"]);
  });
});

test("cycling the order", async (t) => {
  await t.test("goes document → newest → oldest → document", () => {
    assert.equal(nextSort("document"), "newest");
    assert.equal(nextSort("newest"), "oldest");
    assert.equal(nextSort("oldest"), "document");
  });

  await t.test("names each order with a literal key", () => {
    assert.equal(sortLabel("document"), "Document order");
    assert.equal(sortLabel("newest"), "Newest first");
    assert.equal(sortLabel("oldest"), "Oldest first");
  });
});

test("marks as Markdown", async (t) => {
  await t.test("puts the page, the quote and the note in reading order", () => {
    const text = marksToMarkdown(
      [mark({ locator: 4, quote: "the latency budget", note: "worth re-reading" })],
      { unit: "Page", note: "Note: " },
    );
    assert.ok(String(text).includes("**Page 4**"));
    assert.ok(String(text).includes("> the latency budget"));
    assert.ok(String(text).includes("Note: worth re-reading"));
  });

  await t.test("omits an absent note instead of printing an empty label", () => {
    const text = marksToMarkdown([mark({ quote: "only a quote" })], {
      unit: "Page",
      note: "Note: ",
    });
    assert.ok(!String(text).includes("Note:"));
  });

  await t.test("separates several marks with a blank line", () => {
    const text = marksToMarkdown(
      [mark({ annotation_id: "a", locator: 1, quote: "one" }),
       mark({ annotation_id: "b", locator: 2, quote: "two" })],
      { unit: "Page", note: "Note: " },
    );
    assert.equal(text.split("\n\n").length, 2);
  });
});
