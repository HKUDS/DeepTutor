import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReadingProvider, useReading } from "@/context/ReadingContext";
import type { AnnotationDraft, AnnotationItem, MaterialDetail } from "@/lib/reading-api";

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch: api.fetch, apiUrl: (url: string) => url }));

function mark(id: string, note = ""): AnnotationItem {
  return {
    annotation_id: id,
    locator: 1,
    kind: "highlight",
    color: "yellow",
    quote: id,
    note,
    rects: [],
    source_anchor: "",
    author: "user",
    created_at: 1,
    updated_at: 1,
  } as AnnotationItem;
}

const draft: AnnotationDraft = {
  locator: 1,
  kind: "highlight",
  color: "yellow",
  quote: "q",
  note: "edited",
  rects: [],
  source_anchor: "",
  selectors: [],
};

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

/** Start a save whose PUT the test rejects later. */
function beginSave(
  context: { current: ReturnType<typeof useReading> },
  edited: AnnotationItem,
) {
  let rejectSave!: (error: Error) => void;
  api.fetch.mockImplementationOnce(
    () =>
      new Promise<Response>((_resolve, reject) => {
        rejectSave = reject;
      }),
  );
  let saving!: Promise<boolean>;
  act(() => {
    saving = context.current.saveMark(draft, edited);
  });
  return {
    reject: (error: Error) => rejectSave(error),
    saving: () => saving,
  };
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
 * A failed PUT has to roll the list back to what the server holds, not to the
 * object this tab captured before the edit.
 *
 * While the write is pending, a refresh deliberately keeps the local row
 * instead of the server's copy. If that write then fails, restoring the
 * captured row would show a stale note over a newer one another tab wrote —
 * and for a row another tab deleted it would resurrect the mark outright.
 */
describe("rolling back a failed save", () => {
  it("shows the remote note another tab wrote, not the copy captured before the PUT", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("a", "old")]);

    // The reader edits the note; the PUT is in flight and will fail.
    const saving = beginSave(result, mark("a", "edited"));
    expect(result.current.annotations[0].note).toBe("edited");

    // Another tab writes "theirs" and its broadcast makes this tab re-read.
    // The pending merge keeps the local (still unacknowledged) edit, so the
    // remote copy is held back until the PUT settles.
    api.fetch.mockResolvedValueOnce(response([mark("a", "theirs")]));
    await act(async () => {
      broadcast("doc-a");
      await flush();
    });
    expect(result.current.annotations[0].note).toBe("edited");

    // The PUT rejects. The rollback re-reads instead of trusting its capture,
    // so the server's newer note lands.
    api.fetch.mockResolvedValueOnce(response([mark("a", "theirs")]));
    await act(async () => {
      saving.reject(new Error("offline"));
      await saving.saving();
      await flush();
    });

    expect(result.current.annotations).toHaveLength(1);
    expect(result.current.annotations[0].note).toBe("theirs");
    expect(result.current.error).toBe("offline");
  });

  it("leaves a mark another tab deleted gone instead of resurrecting it", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("a", "old")]);

    const saving = beginSave(result, mark("a", "edited"));

    // Another tab deletes the mark. A refresh lands while the PUT is still in
    // flight and returns no rows, but the pending merge keeps this tab's row
    // on screen for now.
    api.fetch.mockResolvedValueOnce(response([]));
    await act(async () => {
      broadcast("doc-a");
      await flush();
    });
    expect(result.current.annotations.map((row) => row.annotation_id)).toEqual(["a"]);

    // The failed PUT must not put the captured row back: the server no longer
    // lists it, and the rollback re-read says so.
    api.fetch.mockResolvedValueOnce(response([]));
    await act(async () => {
      saving.reject(new Error("offline"));
      await saving.saving();
      await flush();
    });

    expect(result.current.annotations).toEqual([]);
    expect(result.current.error).toBe("offline");
  });

  it("does not resurrect a deleted mark when a newer refresh supersedes the re-read", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("a", "old")]);

    const saving = beginSave(result, mark("a", "edited"));

    // Another tab deletes the mark while the PUT is still in flight; the
    // pending merge keeps this tab's row for now.
    api.fetch.mockResolvedValueOnce(response([]));
    await act(async () => {
      broadcast("doc-a");
      await flush();
    });
    expect(result.current.annotations.map((row) => row.annotation_id)).toEqual(["a"]);

    // The PUT rejects and the rollback's re-read starts, but does not answer
    // yet.
    const reconcile = deferred();
    api.fetch.mockReturnValueOnce(reconcile.promise);
    await act(async () => {
      saving.reject(new Error("offline"));
      await flush();
    });

    // A newer refresh lands first and settles the list without the row.
    api.fetch.mockResolvedValueOnce(response([]));
    await act(async () => {
      broadcast("doc-a");
      await flush();
    });
    expect(result.current.annotations).toEqual([]);

    // The older re-read answers last and is superseded. Its rollback must not
    // append the captured row: the server no longer lists it.
    await act(async () => {
      reconcile.resolve(response([]));
      await saving.saving();
      await flush();
    });
    expect(result.current.annotations).toEqual([]);
    expect(result.current.error).toBe("offline");
  });

  it("restores the previous note when the save failed with no remote change", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("a", "old")]);

    // The PUT fails and the reconcile read fails too, so the rollback falls
    // back to the captured row — the behaviour before the re-read existed.
    api.fetch.mockRejectedValueOnce(new Error("offline"));
    api.fetch.mockRejectedValueOnce(new Error("offline"));
    await act(async () => {
      const saved = await result.current.saveMark(draft, mark("a", "edited"));
      expect(saved).toBe(false);
      await flush();
    });

    expect(result.current.annotations).toHaveLength(1);
    expect(result.current.annotations[0].note).toBe("old");
    expect(result.current.error).toBe("offline");
  });
});
