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
  unit_refs: [],
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

describe("the reading outline", () => {
  it("hears about a page turned in the document, not only a row clicked", async () => {
    const onLocatorChange = vi.fn();
    render(<ReaderPane onClose={vi.fn()} onLocatorChange={onLocatorChange} />);

    fireEvent.click(await screen.findByText("turn to section 5"));

    // Without this the workspace's activeLocator stayed wherever the panel
    // last put it, so the outline never left chapter one (#1447).
    expect(onLocatorChange).toHaveBeenCalledWith(5);
  });
});
