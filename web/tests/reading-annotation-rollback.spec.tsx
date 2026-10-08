import React from "react";
import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReadingProvider, useReading } from "@/context/ReadingContext";
import type { AnnotationItem, MaterialDetail } from "@/lib/reading-api";

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch: api.fetch, apiUrl: (url: string) => url }));

let context: ReturnType<typeof useReading>;
function Probe() {
  context = useReading();
  return null;
}

function mark(id: string): AnnotationItem {
  return { annotation_id: id, locator: 1, kind: "highlight", quote: id } as AnnotationItem;
}

async function open(id: string, marks: AnnotationItem[]) {
  api.fetch.mockResolvedValueOnce(new Response(JSON.stringify(marks)));
  await act(async () => {
    await context.openMaterial({ material_id: id, outline: [], revision: 1 } as unknown as MaterialDetail);
  });
}

describe("Reading annotation deletion rollback", () => {
  it("keeps annotations added while a failed deletion is pending", async () => {
    render(<ReadingProvider><Probe /></ReadingProvider>);
    const original = mark("original");
    await open("document-a", [original]);
    let fail!: (error: Error) => void;
    api.fetch.mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
    let pending!: Promise<void>;
    act(() => { pending = context.removeMark(original); });
    act(() => { context.mergeMark(mark("new")); });
    await act(async () => { fail(new Error("Disconnected")); await pending; });
    expect(context.annotations.map(row => row.annotation_id).sort()).toEqual(["new", "original"]);
  });

  it("does not restore the previous document's marks after opening another document", async () => {
    render(<ReadingProvider><Probe /></ReadingProvider>);
    const original = mark("original");
    await open("document-a", [original]);
    let fail!: (error: Error) => void;
    api.fetch.mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
    let pending!: Promise<void>;
    act(() => { pending = context.removeMark(original); });
    await open("document-b", [mark("other-document")]);
    await act(async () => { fail(new Error("Disconnected")); await pending; });
    expect(context.material?.material_id).toBe("document-b");
    expect(context.annotations.map(row => row.annotation_id)).toEqual(["other-document"]);
    expect(context.error).toBeNull();
  });
});
