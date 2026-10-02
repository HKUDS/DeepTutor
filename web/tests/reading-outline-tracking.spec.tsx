import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReaderPane } from "@/components/reading/ReaderPane";
import { initI18n } from "@/i18n/init";

initI18n("en");

const material = {
  material_id: "m-1",
  title: "A Book",
  render_mode: "text",
  unit: "section",
  unit_count: 100,
  unit_refs: [
    { locator: 1, source_href: "chapter-1.xhtml", title: "Opening" },
    { locator: 5, source_href: "chapter-5.xhtml", title: "Second chapter" },
    { locator: 20, source_href: "chapter-20.xhtml", title: "Last chapter" },
  ],
  has_raw_view: false,
  status: "ready",
  source_kind: "upload",
  extractor: "",
};

vi.mock("@/context/ReadingContext", () => ({
  useReading: () => ({
    material,
    annotations: [],
    loading: false,
    error: "",
    openMaterial: vi.fn(),
    closeMaterial: vi.fn(),
    saveMark: vi.fn(),
    removeMark: vi.fn(),
    mergeMark: vi.fn(),
    dismissError: vi.fn(),
    setError: vi.fn(),
    reportViewport: vi.fn(),
  }),
}));

// The text view is the piece that knows which unit is on screen; stand in for
// it with a button that reports one, the way a page turn does.
vi.mock("@/components/reading/TextUnitView", () => ({
  unitLabel: () => "section",
  TextUnitView: ({
    onVisibleLocatorChange,
  }: {
    onVisibleLocatorChange?: (locator: number) => void;
  }) => (
    <button type="button" onClick={() => onVisibleLocatorChange?.(5)}>
      turn to section 5
    </button>
  ),
}));

vi.mock("@/components/reading/EpubDocumentView", () => ({
  EpubDocumentView: ({
    onVisibleLocatorChange,
  }: {
    onVisibleLocatorChange?: (locator: number) => void;
  }) => (
    <button type="button" onClick={() => onVisibleLocatorChange?.(5)}>
      turn epub to chapter 5
    </button>
  ),
}));

describe("the reading outline", () => {
  it("hears about a page turned in the document, not only a row clicked", async () => {
    const onLocatorChange = vi.fn();
    render(<ReaderPane onClose={vi.fn()} onLocatorChange={onLocatorChange} />);

    fireEvent.click(await screen.findByText("turn to section 5"));

    // Without this the workspace's activeLocator stayed wherever the panel
    // last put it, so the outline never left chapter one (#1447).
    expect(onLocatorChange).toHaveBeenCalledWith(5);
  });

  it("labels an EPUB by its current chapter and progress, not spine page count", async () => {
    material.render_mode = "epub";
    material.unit_count = 20;
    render(<ReaderPane onClose={vi.fn()} />);

    fireEvent.click(await screen.findByText("turn epub to chapter 5"));

    expect(screen.getByText("Second chapter")).toBeInTheDocument();
    expect(screen.getByText(/21%/)).toBeInTheDocument();
    expect(screen.queryByText("chapter 5 / 20")).not.toBeInTheDocument();
  });
});
