import { useMarkSelection, toSelectable } from "@/components/reading/useMarkSelection";
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

function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
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
 * A remote refresh is a GET that races everything else this tab is doing.
 *
 * The list it returns is a snapshot of the server at the moment it was
 * issued, so it can be older than a write that has since landed here, older
 * than another refresh, or still list a row whose DELETE is in flight. None
 * of those may be allowed to undo what the reader can see they just did.
 */
describe("a remote refresh racing a local write or another refresh", () => {
  it("does not let an older refresh erase a locally acknowledged creation", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("existing")]);

    // A refresh starts while the server still holds only the old row.
    const old = deferred();
    api.fetch.mockReturnValueOnce(old.promise);
    act(() => {
      broadcast("doc-a");
    });

    // The reader's new mark is created and acknowledged before that GET lands.
    api.fetch.mockResolvedValueOnce(new Response(JSON.stringify(mark("saved-new"))));
    await act(async () => {
      await result.current.saveMark(
        {
          locator: 1,
          kind: "highlight",
          color: "yellow",
          quote: "new",
          note: "",
          rects: [],
          source_anchor: "",
          selectors: [],
        },
        mark("pending-new"),
      );
    });
    expect(result.current.annotations.map((row) => row.annotation_id)).toContain(
      "saved-new",
    );

    await act(async () => {
      old.resolve(response([mark("existing")]));
      await flush();
    });
    // The acknowledged row survives the snapshot that predates it.
    expect(result.current.annotations.map((row) => row.annotation_id)).toContain(
      "saved-new",
    );
  });

  it("does not let an older GET overtake a newer remote refresh", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("existing")]);

    const old = deferred();
    const fresh = deferred();
    api.fetch.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    act(() => {
      broadcast("doc-a");
      broadcast("doc-a");
    });

    // The newer GET answers first, then the older one answers last.
    await act(async () => {
      fresh.resolve(response([mark("existing"), mark("newest")]));
      await flush();
    });
    expect(result.current.annotations.map((row) => row.annotation_id)).toContain(
      "newest",
    );

    await act(async () => {
      old.resolve(response([mark("existing")]));
      await flush();
    });
    // Newest response wins, regardless of arrival order.
    expect(result.current.annotations.map((row) => row.annotation_id)).toContain(
      "newest",
    );
  });

  it("does not resurrect a deleted row when a remote refresh overlaps DELETE", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("a")]);

    // The DELETE is in flight; the server has not removed the row yet.
    const del = deferred();
    api.fetch.mockReturnValueOnce(del.promise);
    let removing!: Promise<boolean>;
    act(() => {
      removing = result.current.removeMark(mark("a"));
    });

    // Another tab's change makes this tab re-read, and that read still sees
    // the row the DELETE is about to remove.
    api.fetch.mockResolvedValueOnce(response([mark("a")]));
    await act(async () => {
      broadcast("doc-a");
      await flush();
    });

    await act(async () => {
      del.resolve(new Response(JSON.stringify({ ok: true })));
      await removing;
    });
    expect(result.current.annotations).toEqual([]);
  });
});

/**
 * A delete the host reports as failed has to reach the bulk caller.
 *
 * `removeMark` already rolls the row back and shows the notice, but if it
 * swallowed the failure the batch walk would count zero failures and the
 * reader would be told nothing happened.
 */
it("reports a production-host delete failure to the bulk caller", async () => {
  const { result } = renderHook(
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

  api.fetch.mockResolvedValueOnce(response([mark("a")]));
  await act(async () => {
    await result.current.reading.openMaterial({
      material_id: "doc-a",
      outline: [],
      revision: 1,
    } as unknown as MaterialDetail);
  });

  act(() => {
    result.current.selection.start();
  });
  act(() => {
    result.current.selection.toggle("a");
  });

  api.fetch.mockRejectedValueOnce(new Error("offline"));
  let failed!: number;
  await act(async () => {
    failed = await result.current.selection.removeSelected();
  });

  expect(result.current.reading.error).toBe("That annotation could not be removed.");
  expect(result.current.reading.annotations.map((row) => row.annotation_id)).toEqual([
    "a",
  ]);
  expect(failed).toBe(1);
});
