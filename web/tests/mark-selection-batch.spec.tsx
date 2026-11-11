import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  toSelectable,
  useMarkSelection,
} from "@/components/reading/useMarkSelection";
import type { AnnotationItem } from "@/lib/reading-api";

function mark(annotation_id: string): AnnotationItem {
  return {
    annotation_id,
    locator: 1,
    kind: "highlight",
    color: "yellow",
    quote: `quote ${annotation_id}`,
    note: "",
    rects: [],
    source_anchor: "",
    author: "user",
    created_at: 1,
    updated_at: 1,
  };
}

/**
 * Starting a batch delete exactly once per press.
 *
 * The API deletes one row per request, so a batch is a walk with an await
 * between rows. A guard read from state is a frame behind: two presses in the
 * same frame both pass it, and every selected row is deleted twice. What
 * matters is that the walk starts once, covers each row once, and that the
 * guard is released afterwards.
 */
describe("removing a selection in one React frame", () => {
  function selection(onDelete: (annotation: AnnotationItem) => Promise<void>) {
    const rows = toSelectable([mark("a"), mark("b")]);
    return renderHook(() => useMarkSelection({ rows, onDelete, onCopy: async () => true }));
  }

  it("starts one walk when two presses land in the same frame", async () => {
    const onDelete = vi.fn<(annotation: AnnotationItem) => Promise<void>>(
      async () => undefined,
    );
    const { result } = selection(onDelete);
    act(() => {
      result.current.start();
      result.current.toggleAll();
    });

    // Both presses are dispatched before React re-renders, so each reads the
    // same state closure; only the ref can turn the second one away.
    await act(async () => {
      await Promise.all([
        result.current.removeSelected(),
        result.current.removeSelected(),
      ]);
    });

    expect(onDelete.mock.calls.map((call) => call[0].annotation_id)).toEqual([
      "a",
      "b",
    ]);
  });

  it("starts a fresh walk once the previous one has settled", async () => {
    const onDelete = vi.fn<(annotation: AnnotationItem) => Promise<void>>(
      async () => undefined,
    );
    const { result } = selection(onDelete);
    act(() => {
      result.current.start();
      result.current.toggleAll();
    });
    await act(async () => {
      await result.current.removeSelected();
    });

    act(() => {
      result.current.start();
      result.current.toggleAll();
    });
    await act(async () => {
      await result.current.removeSelected();
    });

    // The guard has to come back down, or one batch would block every later
    // one for the life of the panel.
    expect(onDelete.mock.calls.map((call) => call[0].annotation_id)).toEqual([
      "a",
      "b",
      "a",
      "b",
    ]);
  });
});

/**
 * Selection follows the rows the reader can actually see.
 *
 * A search or colour filter can hide a selected row. The batch actions only
 * walk visible rows, so a selection that kept hidden ids made the delete cover
 * fewer rows than the count promised — silently, because a batch that deletes
 * everything it attempted reports no failure.
 */
describe("a filter narrowing the list under a selection", () => {
  it("counts only the rows a batch would act on", () => {
    const all = [mark("a"), mark("b"), mark("c")];
    const { result, rerender } = renderHook(
      ({ rows }: { rows: AnnotationItem[] }) =>
        useMarkSelection({
          rows: toSelectable(rows),
          onDelete: async () => true,
          onCopy: async () => true,
        }),
      { initialProps: { rows: all } },
    );
    act(() => result.current.start());
    act(() => result.current.toggleAll());
    expect(result.current.count).toBe(3);

    // The reader searches; only "b" survives the filter.
    rerender({ rows: [mark("b")] });
    expect(result.current.count).toBe(1);
    expect(result.current.allSelected).toBe(true);
  });

  it("deletes exactly the rows the count promised", async () => {
    const deleted: string[] = [];
    const all = [mark("a"), mark("b"), mark("c")];
    const { result, rerender } = renderHook(
      ({ rows }: { rows: AnnotationItem[] }) =>
        useMarkSelection({
          rows: toSelectable(rows),
          onDelete: async (annotation) => {
            deleted.push(annotation.annotation_id);
            return true;
          },
          onCopy: async () => true,
        }),
      { initialProps: { rows: all } },
    );
    act(() => result.current.start());
    act(() => result.current.toggleAll());
    // Filter down to one row, then delete: the two hidden rows must not be
    // counted, and the one visible row must be the one removed.
    rerender({ rows: [mark("b")] });
    let failed = 0;
    await act(async () => {
      failed = await result.current.removeSelected();
    });
    expect(failed).toBe(0);
    expect(deleted).toEqual(["b"]);
  });
});
