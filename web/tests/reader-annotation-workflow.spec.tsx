import { Suspense, lazy, type ComponentType } from "react";
import { act, fireEvent, render, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReaderPane } from "@/components/reading/ReaderPane";

vi.mock("next/dynamic", () => ({ default: (loader: () => Promise<ComponentType>) => lazy(async () => ({ default: await loader() })) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/components/reading/PdfDocumentView", () => ({ PdfDocumentView: () => null }));
vi.mock("@/components/reading/reading-actions-context", () => ({ useReadingActions: () => null }));
vi.mock("@/components/reading/workspace-menu-context", () => ({ useWorkspaceMenuSection: () => false }));
vi.mock("@/components/reading/ReadingExtensionBar", () => ({ ReadingExtensionBar: () => null }));
vi.mock("@/lib/reading-api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/reading-api")>(),
  getReadingPosition: async () => null,
}));

const reading = vi.hoisted(() => ({
  material: {
    material_id: "m1", title: "Book", filename: "book.pdf", unit: "page",
    unit_count: 2, revision: 1, has_raw_view: true, render_mode: "pdf",
  },
  annotations: [{
    annotation_id: "a1", locator: 1, kind: "highlight", color: "yellow",
    quote: "A passage", note: "Original note", rects: [], source_anchor: "",
    selectors: [], author: "user", created_at: 1, updated_at: 2,
  }],
  loading: false, error: null,
  openMaterial: vi.fn(), closeMaterial: vi.fn(), saveMark: vi.fn(async () => true),
  removeMark: vi.fn(async () => undefined), mergeMark: vi.fn(),
  dismissError: vi.fn(), setError: vi.fn(), reportViewport: vi.fn(),
}));
vi.mock("@/context/ReadingContext", () => ({ useReading: () => reading }));

describe("ReaderPane's own annotation list", () => {
  it("edits notes and mark appearance through the conditional save path", async () => {
    const view = render(<Suspense fallback={null}><ReaderPane onClose={() => {}} /></Suspense>);
    const edit = await view.findByRole("button", { name: "Edit note" });
    expect(view.getByRole("searchbox", { name: "Search annotations…" })).toBeInTheDocument();
    fireEvent.click(edit);
    fireEvent.change(await view.findByTestId("annotation-note-input"), { target: { value: "Revised note" } });
    await act(async () => { fireEvent.click(view.getByRole("button", { name: "Save note" })); });
    await waitFor(() => expect(reading.saveMark).toHaveBeenCalledWith(
      expect.objectContaining({ annotation_id: "a1", note: "Revised note", expected_updated_at: 2 }),
      expect.objectContaining({ annotation_id: "a1", note: "Revised note", quote: "A passage" }),
    ));
    const palette = within(view.getByRole("group", { name: "Change colour" }));
    await act(async () => { fireEvent.click(palette.getByRole("button", { name: "Blue" })); });
    expect(reading.saveMark).toHaveBeenLastCalledWith(
      expect.objectContaining({ color: "blue", expected_updated_at: 2 }),
      expect.objectContaining({ color: "blue", note: "Original note" }),
    );
    await act(async () => { fireEvent.click(palette.getByRole("button", { name: "Underline" })); });
    expect(reading.saveMark).toHaveBeenLastCalledWith(
      expect.objectContaining({ kind: "underline", expected_updated_at: 2 }),
      expect.objectContaining({ kind: "underline", quote: "A passage" }),
    );
  });
});
