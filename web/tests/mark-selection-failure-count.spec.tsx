import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  toSelectable,
  useMarkSelection,
} from "@/components/reading/useMarkSelection";
import { ReadingProvider, useReading } from "@/context/ReadingContext";
import type { AnnotationItem, MaterialDetail } from "@/lib/reading-api";

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch: api.fetch, apiUrl: (url: string) => url }));

function mark(id: string): AnnotationItem {
  return {
    annotation_id: id,
    locator: 1,
    kind: "highlight",
    color: "yellow",
    quote: id,
    note: "",
    rects: [],
    source_anchor: "",
    author: "user",
    created_at: 1,
    updated_at: 1,
  } as AnnotationItem;
}

async function open(
  context: { current: { reading: ReturnType<typeof useReading> } },
  id: string,
  marks: AnnotationItem[],
) {
  api.fetch.mockResolvedValueOnce(new Response(JSON.stringify(marks)));
  await act(async () => {
    await context.current.reading.openMaterial({
      material_id: id,
      outline: [],
      revision: 1,
    } as unknown as MaterialDetail);
  });
}

function host() {
  return renderHook(
    () => {
      const reading = useReading();
      const selection = useMarkSelection({
        rows: toSelectable(reading.annotations),
        onDelete: reading.removeMark,
        onCopy: async () => true,
      });
      return { reading, selection };
    },
    { wrapper: ReadingProvider },
  );
}

beforeEach(() => {
  api.fetch.mockReset();
});

/**
 * What a bulk delete counts.
 *
 * A host reports a failed delete by rolling its row back and resolving
 * `false`; it does not reject. Counting only rejections made a batch of
 * failures report `failed = 0`, so the reader saw the row come back and the
 * notice appear while the count claimed nothing had gone wrong.
 */
describe("counting a failed bulk delete", () => {
  it("counts the failure, restores the row, and shows the notice", async () => {
    const { result } = host();
    await open(result, "document-a", [mark("a")]);

    act(() => {
      result.current.selection.start();
      result.current.selection.toggle("a");
    });

    api.fetch.mockRejectedValueOnce(new Error("offline"));
    let failed!: number;
    await act(async () => {
      failed = await result.current.selection.removeSelected();
    });

    expect(failed).toBe(1);
    // The reader already rolled the row back; the count has to agree.
    expect(
      result.current.reading.annotations.map((row) => row.annotation_id),
    ).toEqual(["a"]);
    expect(result.current.reading.error).toBe(
      "That annotation could not be removed.",
    );
  });

  it("counts nothing when the delete succeeds", async () => {
    const { result } = host();
    await open(result, "document-a", [mark("a")]);

    act(() => {
      result.current.selection.start();
      result.current.selection.toggle("a");
    });

    api.fetch.mockResolvedValueOnce(new Response("null"));
    let failed!: number;
    await act(async () => {
      failed = await result.current.selection.removeSelected();
    });

    expect(failed).toBe(0);
    expect(result.current.reading.annotations).toEqual([]);
    expect(result.current.reading.error).toBeNull();
  });
});
