import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

/** Storage events only reach *other* tabs, so the tests dispatch them directly. */
function broadcast(materialId: string) {
  window.dispatchEvent(
    new StorageEvent("storage", {
      key: "dt.reader.annotationsRevision",
      newValue: JSON.stringify({ materialId, at: Date.now() }),
    }),
  );
}

async function open(
  context: { current: ReturnType<typeof useReading> },
  id: string,
  marks: AnnotationItem[],
) {
  api.fetch.mockResolvedValueOnce(new Response(JSON.stringify(marks)));
  await act(async () => {
    await context.current.openMaterial({
      material_id: id,
      outline: [],
      revision: 1,
    } as unknown as MaterialDetail);
  });
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const response = (rows: AnnotationItem[]) => new Response(JSON.stringify(rows));

beforeEach(() => {
  api.fetch.mockReset();
  localStorage.clear();
});
afterEach(() => {
  localStorage.clear();
});

/**
 * A failed DELETE has to roll the row back to what the server holds.
 *
 * The row this tab captured when the DELETE left can be older than the server:
 * another tab may have edited the mark while the request was in flight, and a
 * refresh may already have brought the newer copy here. Restoring the captured
 * object would put the old note back on screen over the newer one, and the
 * reader would see a stale mark until the next refresh or reopen.
 */
describe("a failed delete after a remote edit", () => {
  it("restores the server's note, not the copy captured before the DELETE", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [{ ...mark("a"), note: "old" }]);

    // The DELETE is in flight and will fail.
    let rejectDelete!: (error: Error) => void;
    api.fetch.mockImplementationOnce(
      () => new Promise<Response>((_resolve, reject) => {
        rejectDelete = reject;
      }),
    );
    let removing!: Promise<boolean>;
    act(() => {
      removing = result.current.removeMark(result.current.annotations[0]);
    });

    // Another tab edits the same mark; the refresh lands the newer row here,
    // where the tombstone still hides it until the DELETE settles.
    api.fetch.mockResolvedValueOnce(
      response([{ ...mark("a"), note: "edited remotely" }]),
    );
    await act(async () => {
      broadcast("doc-a");
      await flush();
    });
    expect(result.current.annotations).toEqual([]);

    // The DELETE fails, so this tab re-reads instead of trusting its capture.
    api.fetch.mockResolvedValueOnce(
      response([{ ...mark("a"), note: "edited remotely" }]),
    );
    await act(async () => {
      rejectDelete(new Error("offline"));
      await removing;
      await flush();
    });

    expect(result.current.annotations).toHaveLength(1);
    expect(result.current.annotations[0].note).toBe("edited remotely");
    // The reader is still told the delete failed.
    expect(result.current.error).toBe("That annotation could not be removed.");
  });

  it("falls back to the captured row when the re-read fails too", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [{ ...mark("a"), note: "old" }]);

    api.fetch.mockRejectedValueOnce(new Error("offline"));
    // The re-read that follows the failed DELETE fails as well.
    api.fetch.mockRejectedValueOnce(new Error("offline"));
    await act(async () => {
      const removed = await result.current.removeMark(result.current.annotations[0]);
      expect(removed).toBe(false);
    });

    // A mark the server may still hold must not vanish because a GET failed.
    expect(result.current.annotations).toHaveLength(1);
    expect(result.current.annotations[0].note).toBe("old");
    expect(result.current.error).toBe("That annotation could not be removed.");
  });
});

/**
 * A mark still being created must not be deleted by its optimistic id.
 *
 * A brand-new mark lives under `pending-…` until its PUT returns. Deleting it
 * then sent that id to the server, which had never seen it: the DELETE 404'd
 * while the PUT created the real row, leaving a mark the server holds and this
 * tab has hidden — invisible until something else refreshed the list.
 */
describe("deleting a mark whose create is still in flight", () => {
  it("waits for the create, then deletes the id the server minted", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", []);

    // The create is in flight and will succeed with the server's own id.
    let resolveCreate!: (value: Response) => void;
    api.fetch.mockImplementationOnce(
      () => new Promise<Response>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const optimistic = { ...mark("pending-1"), quote: "fresh" };
    let saving!: Promise<boolean>;
    act(() => {
      saving = result.current.saveMark(
        { locator: 1, quote: "fresh" },
        optimistic,
      );
    });
    expect(result.current.annotations.map((row) => row.annotation_id)).toEqual([
      "pending-1",
    ]);

    // The reader deletes it before the PUT has returned.
    let removing!: Promise<boolean>;
    act(() => {
      removing = result.current.removeMark(result.current.annotations[0]);
    });

    // The create lands with the real id; the delete must now name that id.
    api.fetch.mockImplementationOnce(() => Promise.resolve(new Response("{}")));
    await act(async () => {
      resolveCreate(new Response(JSON.stringify({ ...mark("real-1"), quote: "fresh" })));
      await saving;
      await removing;
      await flush();
    });

    const calls = api.fetch.mock.calls.map((call) => [
      String(call[1]?.method ?? "GET"),
      String(call[0]),
    ]);
    // A DELETE went out, and it named the server's id — never `pending-1`.
    const deletes = calls.filter(([method]) => method === "DELETE");
    expect(deletes).toHaveLength(1);
    expect(deletes[0][1]).toContain("real-1");
    expect(deletes[0][1]).not.toContain("pending-1");
    expect(result.current.annotations).toEqual([]);
  });
});
