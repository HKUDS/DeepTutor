import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

/**
 * Below `lg` the annotation column cannot fit beside the page, so the reader
 * draws the same list as a bottom sheet. Before this, the ⋯ menu's
 * "Annotations" toggle flipped state that only a `hidden lg:block` column
 * consumed, so on a phone the control did nothing at all.
 */

const device = vi.hoisted(() => ({ isMobile: true, isTablet: false }));

vi.mock("@/hooks/useDevice", () => ({
  useDevice: () => ({
    device: device.isTablet ? "tablet" : device.isMobile ? "mobile" : "desktop",
    isMobile: device.isMobile,
    isTablet: device.isTablet,
    isDesktop: !device.isMobile && !device.isTablet,
    // mobile || tablet — the "no room for a second column" test.
    isCompact: device.isMobile || device.isTablet,
  }),
}));

vi.mock("@/components/reading/PdfDocumentView", () => ({
  PdfDocumentView: () => <div data-testid="doc" />,
}));

vi.mock("@/components/reading/EpubDocumentView", () => ({
  EpubDocumentView: () => null,
}));

vi.mock("@/components/reading/TextUnitView", () => ({
  TextUnitView: () => null,
  unitLabel: () => "page",
}));

const listCalls = vi.hoisted(() => ({ count: 0 }));

vi.mock("@/components/reading/AnnotationList", () => ({
  AnnotationList: () => {
    listCalls.count += 1;
    return <div data-testid="annotation-list" />;
  },
}));

vi.mock("@/lib/auth", () => ({ fetchAuthStatus: vi.fn(async () => null) }));

vi.mock("@/lib/reading-api", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchExport: vi.fn(),
  getMaterial: vi.fn(async () => null),
  getReadingPosition: vi.fn(async () => ({ locator: 1, source_anchor: "" })),
  saveReadingPosition: vi.fn(),
}));

const material = {
  material_id: "0123456789abcdef",
  title: "Understanding Deep Learning",
  filename: "udl.pdf",
  unit: "page",
  mime: "application/pdf",
  render_mode: "raw",
  has_raw_view: true,
  unit_count: 10,
};

const marks = vi.hoisted(() => ({
  rows: [
    {
      annotation_id: "a1",
      locator: 2,
      kind: "highlight",
      color: "yellow",
      quote: "the gradient flows backwards",
      note: "worth re-reading",
      rects: [],
      source_anchor: "",
      author: "user",
      created_at: 1,
      updated_at: 1,
    },
  ],
}));

vi.mock("@/context/ReadingContext", () => ({
  useReading: () => ({
    material,
    annotations: marks.rows,
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

const { ReaderPane } = await import("@/components/reading/ReaderPane");

describe("annotations on a phone", () => {
  it("draws the list as an overlay, since a phone has no room for a column", async () => {
    device.isMobile = true;
    listCalls.count = 0;
    render(<ReaderPane onClose={() => undefined} onToggleBookmark={() => undefined} />);

    // A material with marks opens the panel from the first render, so the
    // overlay is what a phone sees instead of a docked column.
    const sheet = await screen.findByRole("dialog", { name: "Annotations" });
    expect(sheet).toBeTruthy();
    expect(screen.getByTestId("annotation-list")).toBeTruthy();
  });

  it("closes and reopens from the ⋯ menu's toggle", async () => {
    device.isMobile = true;
    render(<ReaderPane onClose={() => undefined} onToggleBookmark={() => undefined} />);
    await screen.findByRole("dialog", { name: "Annotations" });

    fireEvent.click(screen.getByLabelText("More"));
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: /Annotations/ }));
    await waitFor(() => expect(screen.queryByTestId("annotation-list")).toBeNull());

    fireEvent.click(screen.getByLabelText("More"));
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: /Annotations/ }));
    await screen.findByRole("dialog", { name: "Annotations" });
  });

  it("closes on the sheet's own close button", async () => {
    device.isMobile = true;
    render(<ReaderPane onClose={() => undefined} onToggleBookmark={() => undefined} />);
    const sheet = await screen.findByRole("dialog", { name: "Annotations" });
    fireEvent.click(sheet.querySelector('button[aria-label="Close"]')!);
    await waitFor(() => expect(screen.queryByTestId("annotation-list")).toBeNull());
  });

  it("closes when the backdrop is tapped, but not when the sheet itself is", async () => {
    device.isMobile = true;
    render(<ReaderPane onClose={() => undefined} onToggleBookmark={() => undefined} />);
    const sheet = await screen.findByRole("dialog", { name: "Annotations" });
    // A tap inside the sheet is the reader working with their marks.
    fireEvent.click(screen.getByTestId("annotation-list"));
    expect(screen.getByTestId("annotation-list")).toBeTruthy();

    fireEvent.click(sheet);
    await waitFor(() => expect(screen.queryByTestId("annotation-list")).toBeNull());
  });

  it("does not draw the desktop column as well", async () => {
    device.isMobile = true;
    render(<ReaderPane onClose={() => undefined} onToggleBookmark={() => undefined} />);
    await screen.findByRole("dialog", { name: "Annotations" });
    // One panel, not two: the mobile branch must not also mount the aside.
    expect(screen.getAllByTestId("annotation-list")).toHaveLength(1);
  });

  it("closes on Escape, like the modal it declares itself to be", async () => {
    device.isMobile = true;
    render(<ReaderPane onClose={() => undefined} onToggleBookmark={() => undefined} />);
    await screen.findByRole("dialog", { name: "Annotations" });
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("annotation-list")).toBeNull());
  });

  it("takes focus into the sheet and hands it back on close", async () => {
    device.isMobile = true;
    render(<ReaderPane onClose={() => undefined} onToggleBookmark={() => undefined} />);
    const sheet = await screen.findByRole("dialog", { name: "Annotations" });
    // A modal that leaves focus behind it strands a keyboard user.
    await waitFor(() => expect(document.activeElement).toBe(sheet));
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("annotation-list")).toBeNull());
    expect(document.activeElement).not.toBe(sheet);
  });

  it("leaves the desktop docked column to the desktop branch", async () => {
    device.isMobile = false;
    render(<ReaderPane onClose={() => undefined} onToggleBookmark={() => undefined} />);
    // With marks present the desktop column is up from the first render; no
    // dialog is involved.
    await waitFor(() => expect(screen.queryByTestId("annotation-list")).not.toBeNull());
    expect(screen.queryByRole("dialog", { name: "Annotations" })).toBeNull();
  });
});


/**
 * Between 768 and 1023px the docked column does not fit and the phone sheet
 * used to be gated on `isMobile` (<768), so neither mounted and the reader's
 * marks were unreachable on a tablet in portrait. The sheet keys on
 * `isCompact` now.
 */
describe("annotations on a tablet", () => {
  it("draws the sheet rather than nothing at 768-1023px", async () => {
    device.isMobile = false;
    device.isTablet = true;
    render(<ReaderPane onClose={() => undefined} onToggleBookmark={() => undefined} />);
    const sheet = await screen.findByRole("dialog", { name: "Annotations" });
    expect(sheet).toBeTruthy();
    expect(screen.getByTestId("annotation-list")).toBeTruthy();
    device.isTablet = false;
  });
});
