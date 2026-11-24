import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { NotebookSummary } from "@/lib/notebook-api";

const api = vi.hoisted(() => ({
  list: async (): Promise<NotebookSummary[]> => [],
}));

vi.mock("@/lib/notebook-api", () => ({
  listNotebooks: () => api.list(),
  getNotebook: vi.fn(),
  createNotebook: vi.fn(),
  updateNotebook: vi.fn(),
  deleteNotebook: vi.fn(),
  updateNotebookRecord: vi.fn(),
  deleteNotebookRecord: vi.fn(),
  relocateNotebookRecord: vi.fn(),
}));

import { useNotebookLibrary } from "@/components/notebook/useNotebookLibrary";

describe("notebook library cache", () => {
  it("serves the cached list instantly on a later visit while refreshing behind it", async () => {
    const notebooks: NotebookSummary[] = [
      { id: "n1", name: "Lecture", record_count: 2 },
    ];
    api.list = async () => notebooks;

    const first = renderHook(() => useNotebookLibrary());
    expect(first.result.current.loading).toBe(true);
    await waitFor(() => expect(first.result.current.loading).toBe(false));
    expect(first.result.current.notebooks).toEqual(notebooks);
    first.unmount();

    // A second visit must not flash a spinner: the cached list paints first
    // and the background reload updates it afterwards.
    const second = renderHook(() => useNotebookLibrary());
    expect(second.result.current.loading).toBe(false);
    expect(second.result.current.notebooks).toEqual(notebooks);
    // Let the background reload settle so it cannot warn outside act().
    await act(async () => {});
  });
});
