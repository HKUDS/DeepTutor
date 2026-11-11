import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReadingProvider, useReading } from "@/context/ReadingContext";
import {
  publishAnnotationsChange,
  subscribeToAnnotationsChange,
} from "@/lib/reading-annotation-sync";
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

beforeEach(() => {
  api.fetch.mockReset();
  localStorage.clear();
});
afterEach(() => {
  localStorage.clear();
});

/**
 * Two tabs on one document each keep their own copy of the marks. Without a
 * signal between them, a mark saved in one is invisible in the other, and an
 * edit made from the second tab writes over the first tab's stale view.
 */
describe("marks kept in step across tabs", () => {
  it("re-reads the marks when another tab reports a change", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("original")]);

    api.fetch.mockResolvedValueOnce(
      new Response(JSON.stringify([mark("original"), mark("added-elsewhere")])),
    );
    await act(async () => {
      broadcast("doc-a");
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(result.current.annotations.map((row) => row.annotation_id).sort()).toEqual([
      "added-elsewhere",
      "original",
    ]);
  });

  it("ignores a change reported for a different document", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("original")]);

    api.fetch.mockResolvedValueOnce(
      new Response(JSON.stringify([mark("other-document")])),
    );
    await act(async () => {
      broadcast("doc-b");
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(result.current.annotations.map((row) => row.annotation_id)).toEqual([
      "original",
    ]);
  });

  it("does not repopulate a closed document with a late refresh", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("original")]);

    let settle!: (value: Response) => void;
    api.fetch.mockImplementationOnce(
      () => new Promise<Response>((resolve) => {
        settle = resolve;
      }),
    );
    act(() => {
      broadcast("doc-a");
    });
    // The reader closes the document while the refresh is in flight.
    act(() => {
      result.current.closeMaterial();
    });
    await act(async () => {
      settle(new Response(JSON.stringify([mark("stale")])));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(result.current.annotations).toEqual([]);
  });

  it("leaves the local list alone when the refresh fails", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("original")]);

    api.fetch.mockImplementationOnce(async () => {
      throw new Error("offline");
    });
    await act(async () => {
      broadcast("doc-a");
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    // A failed refresh must not empty the list the reader is looking at.
    expect(result.current.annotations.map((row) => row.annotation_id)).toEqual([
      "original",
    ]);
    expect(result.current.error).toBeNull();
  });
});

describe("announcing a change", () => {
  it("writes a revision marker another tab can see", () => {
    publishAnnotationsChange("doc-a");
    const raw = localStorage.getItem("dt.reader.annotationsRevision");
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!)).toMatchObject({ materialId: "doc-a" });
  });

  it("never writes the same value twice, even within one millisecond", () => {
    // A `storage` event only fires when the value actually changes, so two
    // saves in the same millisecond would make the second one silent.
    publishAnnotationsChange("doc-a");
    const first = localStorage.getItem("dt.reader.annotationsRevision");
    publishAnnotationsChange("doc-a");
    const second = localStorage.getItem("dt.reader.annotationsRevision");
    expect(first).not.toBe(second);
    expect(JSON.parse(second!).seq).toBeGreaterThan(JSON.parse(first!).seq);
  });

  it("carries a per-tab identity so two tabs never write the same payload", () => {
    // `seq` alone is a per-tab counter: two tabs both start at 1, and in the
    // same millisecond the payloads would be byte-identical — `setItem` sees no
    // change, no event fires, and the second tab's write is lost silently.
    publishAnnotationsChange("doc-a");
    const payload = JSON.parse(
      localStorage.getItem("dt.reader.annotationsRevision")!,
    );
    expect(payload.tab).toBeTruthy();
    expect(typeof payload.tab).toBe("string");
    // The counter and the timestamp are both in play; the tab id is the part
    // that makes two independent tabs differ.
    expect(payload.seq).toBeGreaterThan(0);
    expect(payload.at).toBeGreaterThan(0);
  });

  it("subscribes only while a document is open", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToAnnotationsChange(null, listener);
    broadcast("doc-a");
    expect(listener).not.toHaveBeenCalled();
    unsubscribe();
  });

  it("stops listening once unsubscribed", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToAnnotationsChange("doc-a", listener);
    broadcast("doc-a");
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    broadcast("doc-a");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("ignores a malformed payload instead of throwing", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToAnnotationsChange("doc-a", listener);
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "dt.reader.annotationsRevision",
        newValue: "not json",
      }),
    );
    expect(listener).not.toHaveBeenCalled();
    unsubscribe();
  });
});

/**
 * A refresh that lands while one of our own writes is in flight.
 *
 * The refresh replaces the whole list with what the server returned, and the
 * server has not acknowledged our row yet. For an edit that is a flicker; for
 * a brand-new mark it is permanent, because the PUT that follows maps by an
 * optimistic id the refresh just removed.
 */
describe("a remote refresh during a local write", () => {
  it("keeps a brand-new mark that the server has not acknowledged yet", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("existing")]);

    // The reader draws a new mark: optimistic id, PUT in flight.
    let settle!: (value: Response) => void;
    api.fetch.mockImplementationOnce(
      () => new Promise<Response>((resolve) => {
        settle = resolve;
      }),
    );
    let saving!: Promise<boolean>;
    act(() => {
      saving = result.current.saveMark(
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
      "pending-new",
    );

    // Another tab broadcasts; this tab re-reads and the server does not know
    // the pending row yet.
    api.fetch.mockResolvedValueOnce(new Response(JSON.stringify([mark("existing")])));
    await act(async () => {
      broadcast("doc-a");
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    // Without the merge the optimistic row is gone here, and the PUT below
    // cannot bring it back.
    expect(result.current.annotations.map((row) => row.annotation_id)).toContain(
      "pending-new",
    );

    await act(async () => {
      settle(new Response(JSON.stringify(mark("server-real"))));
      await saving;
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(result.current.annotations.map((row) => row.annotation_id)).toEqual(
      expect.arrayContaining(["existing", "server-real"]),
    );
  });
});

describe("the marker's storage area", () => {
  it("ignores a same-named key written to sessionStorage", () => {
    // The shared subscriber guards on `storageArea`; this listener must too,
    // or an unrelated sessionStorage write would look like a mark change.
    const listener = vi.fn();
    const unsubscribe = subscribeToAnnotationsChange("doc-a", listener);
    // jsdom refuses a `storageArea` in the constructor, so build the event and
    // attach the area afterwards.
    const event = new StorageEvent("storage", {
      key: "dt.reader.annotationsRevision",
      newValue: JSON.stringify({ materialId: "doc-a", at: Date.now(), seq: 1 }),
    });
    Object.defineProperty(event, "storageArea", {
      value: window.sessionStorage,
      configurable: true,
    });
    window.dispatchEvent(event);
    expect(listener).not.toHaveBeenCalled();
    unsubscribe();
  });
});

describe("the assistant's marks", () => {
  it("announces a merged mark so the other tabs hear about it", async () => {
    // The assistant's mark is already persisted by the tool that made it, so
    // it is a real change and must broadcast like a reader-saved one.
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", []);
    act(() => {
      result.current.mergeMark(mark("from-assistant"));
    });
    const raw = localStorage.getItem("dt.reader.annotationsRevision");
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!)).toMatchObject({ materialId: "doc-a" });
  });
});

describe("the other write paths", () => {
  it("announces a removal", async () => {
    // saveMark and mergeMark both broadcast; a removal is just as much a change
    // to the document's marks.
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("a1")]);
    api.fetch.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })));
    await act(async () => {
      await result.current.removeMark(result.current.annotations[0]);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const raw = localStorage.getItem("dt.reader.annotationsRevision");
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!)).toMatchObject({ materialId: "doc-a" });
  });

  it("does not announce a removal that failed", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("a1")]);
    api.fetch.mockImplementationOnce(async () => {
      throw new Error("offline");
    });
    await act(async () => {
      await result.current.removeMark(result.current.annotations[0]);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    // A failed delete rolls the row back; telling other tabs would make them
    // drop a mark that is still there.
    expect(localStorage.getItem("dt.reader.annotationsRevision")).toBeNull();
    expect(result.current.annotations.map((row) => row.annotation_id)).toEqual(["a1"]);
  });
});
