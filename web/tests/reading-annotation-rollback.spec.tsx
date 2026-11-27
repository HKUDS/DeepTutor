import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReadingProvider, useReading } from "@/context/ReadingContext";
import type { AnnotationItem, MaterialDetail } from "@/lib/reading-api";

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch: api.fetch, apiUrl: (url: string) => url }));

function mark(id: string): AnnotationItem {
  return { annotation_id: id, locator: 1, kind: "highlight", quote: id } as AnnotationItem;
}

async function open(context: { current: ReturnType<typeof useReading> }, id: string, marks: AnnotationItem[]) {
  api.fetch.mockResolvedValueOnce(new Response(JSON.stringify(marks)));
  await act(async () => {
    await context.current.openMaterial({ material_id: id, outline: [], revision: 1 } as unknown as MaterialDetail);
  });
}

describe("Reading annotation deletion rollback", () => {
  it("keeps annotations added while a failed deletion is pending", async () => {
    const { result: context } = renderHook(useReading, { wrapper: ReadingProvider });
    const original = mark("original");
    await open(context, "document-a", [original]);
    let fail!: (error: Error) => void;
    api.fetch.mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
    let pending!: Promise<boolean>;
    act(() => { pending = context.current.removeMark(original); });
    act(() => { context.current.mergeMark(mark("new")); });
    await act(async () => { fail(new Error("Disconnected")); await pending; });
    expect(context.current.annotations.map(row => row.annotation_id).sort()).toEqual(["new", "original"]);
  });

  it("does not restore the previous document's marks after opening another document", async () => {
    const { result: context } = renderHook(useReading, { wrapper: ReadingProvider });
    const original = mark("original");
    await open(context, "document-a", [original]);
    let fail!: (error: Error) => void;
    api.fetch.mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
    let pending!: Promise<boolean>;
    act(() => { pending = context.current.removeMark(original); });
    await open(context, "document-b", [mark("other-document")]);
    await act(async () => { fail(new Error("Disconnected")); await pending; });
    expect(context.current.material?.material_id).toBe("document-b");
    expect(context.current.annotations.map(row => row.annotation_id)).toEqual(["other-document"]);
    expect(context.current.error).toBeNull();
  });
});

describe("Reading annotation save rollback", () => {
  const draft = {
    locator: 1,
    kind: "highlight" as const,
    color: "yellow",
    quote: "q",
    note: "",
    rects: [],
    source_anchor: "",
    selectors: [],
  };

  it("puts a new mark back out of the list when the write fails", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", []);
    api.fetch.mockImplementationOnce(async () => {
      throw new Error("Disconnected");
    });
    const optimistic = { ...mark("pending-1"), ...draft } as AnnotationItem;
    await act(async () => {
      const saved = await result.current.saveMark(draft, optimistic);
      expect(saved).toBe(false);
    });
    // A mark that never reached the server must not stay on screen.
    expect(result.current.annotations).toEqual([]);
    expect(result.current.error).toBe("Disconnected");
  });

  it("restores the previous row when an edit fails", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", [mark("a1")]);
    api.fetch.mockImplementationOnce(async () => {
      throw new Error("Disconnected");
    });
    const edited = { ...mark("a1"), note: "edited" } as AnnotationItem;
    await act(async () => {
      await result.current.saveMark({ ...draft, annotation_id: "a1", note: "edited" }, edited);
    });
    // The row keeps its old content, and is still there.
    expect(result.current.annotations.map((row) => row.annotation_id)).toEqual(["a1"]);
  });

  it("reports a non-Error rejection with a fallback message", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    await open(result, "doc-a", []);
    api.fetch.mockImplementationOnce(async () => {
      throw "not an Error";
    });
    await act(async () => {
      await result.current.saveMark(draft, { ...mark("pending-2"), ...draft } as AnnotationItem);
    });
    expect(result.current.error).toBe("That annotation could not be saved.");
  });
});

describe("Reading document open races", () => {
  it("reports a failed open with a fallback message for a non-Error", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider });
    api.fetch.mockImplementationOnce(async () => {
      throw "boom";
    });
    await act(async () => {
      const opened = await result.current.openMaterial("doc-x");
      expect(opened).toBe(false);
    });
    expect(result.current.error).toBe("This document could not be opened.");
    expect(result.current.loading).toBe(false);
    expect(result.current.material).toBeNull();
  });
});
