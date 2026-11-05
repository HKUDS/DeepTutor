import { describe, expect, it } from "vitest";
import { buildMarkUpdate } from "@/lib/reading-mark-update";
import type { AnnotationItem } from "@/lib/reading-api";

function mark(overrides: Partial<AnnotationItem> = {}): AnnotationItem {
  return {
    annotation_id: "a1",
    locator: 3,
    kind: "highlight",
    color: "yellow",
    quote: "the latency budget",
    note: "original",
    rects: [[0.1, 0.2, 0.5, 0.24]],
    source_anchor: "",
    selectors: [],
    author: "user",
    created_at: 10,
    updated_at: 10,
    ...overrides,
  } as AnnotationItem;
}

/**
 * The rule every surface that edits a mark shares.
 *
 * Its callers (the reader pane and the workspace navigator) are mocked in the
 * component tests, so nothing exercised this function directly — the CRAP
 * report showed 0% coverage on a function that decides whether a highlight
 * moves. The node:test twin lives in `reading-mark-update.test.ts`; this spec
 * is what puts it on the vitest coverage map.
 */
describe("buildMarkUpdate", () => {
  it("keeps everything that anchors the mark", () => {
    const update = buildMarkUpdate(mark(), { note: "revised" });
    expect(update).not.toBeNull();
    expect(update!.draft.note).toBe("revised");
    expect(update!.draft.quote).toBe("the latency budget");
    expect(update!.draft.rects).toEqual([[0.1, 0.2, 0.5, 0.24]]);
    expect(update!.draft.locator).toBe(3);
    expect(update!.draft.annotation_id).toBe("a1");
    expect(update!.optimistic.created_at).toBe(10);
  });

  it("trims the note it sends", () => {
    expect(buildMarkUpdate(mark(), { note: "  spaced  " })!.draft.note).toBe("spaced");
  });

  it("bumps updated_at on a real change", () => {
    expect(buildMarkUpdate(mark(), { color: "green" })!.optimistic.updated_at).toBeGreaterThan(10);
  });

  it("reports no update when nothing actually changed", () => {
    expect(buildMarkUpdate(mark(), { note: "original" })).toBeNull();
    expect(buildMarkUpdate(mark(), { color: "yellow" })).toBeNull();
    expect(buildMarkUpdate(mark(), { kind: "highlight" })).toBeNull();
    expect(buildMarkUpdate(mark(), {})).toBeNull();
  });

  it("refuses to wipe a note by emptying it", () => {
    expect(buildMarkUpdate(mark(), { note: "" })).toBeNull();
    expect(buildMarkUpdate(mark(), { note: "   " })).toBeNull();
  });

  it("changes the colour without touching the note", () => {
    const update = buildMarkUpdate(mark(), { color: "green" })!;
    expect(update.draft.color).toBe("green");
    expect(update.draft.note).toBe("original");
  });

  it("changes the kind", () => {
    expect(buildMarkUpdate(mark(), { kind: "underline" })!.draft.kind).toBe("underline");
  });

  it("applies several changes at once", () => {
    const update = buildMarkUpdate(mark(), {
      note: "new",
      color: "blue",
      kind: "underline",
    })!;
    expect(update.draft.note).toBe("new");
    expect(update.draft.color).toBe("blue");
    expect(update.draft.kind).toBe("underline");
  });

  it("defaults selectors to an empty list", () => {
    expect(buildMarkUpdate(mark({ selectors: undefined }), { color: "pink" })!.draft.selectors).toEqual([]);
  });
});
