import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

const fixture = vi.hoisted(() => {
  const rendition = {
    display: vi.fn(async (_target?: string) => undefined),
    currentLocation: vi.fn(() => ({ start: { cfi: "epubcfi(/6/2)" } })),
    next: vi.fn(async () => undefined),
    prev: vi.fn(async () => undefined),
    resize: vi.fn(),
    spread: vi.fn(),
    destroy: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    annotations: { highlight: vi.fn(), remove: vi.fn() },
    hooks: { content: { register: vi.fn() } },
    themes: {
      registerCss: vi.fn(),
      select: vi.fn(),
      fontSize: vi.fn(),
      override: vi.fn(),
    },
  };
  return {
    rendition,
    renderTo: vi.fn(() => rendition),
    apiFetch: vi.fn(async () => ({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(8),
    })),
  };
});

vi.mock("epubjs", () => ({
  default: () => ({
    open: async () => undefined,
    ready: Promise.resolve(),
    renderTo: fixture.renderTo,
    spine: { get: () => ({ href: "one.xhtml" }) },
    destroy: vi.fn(),
  }),
}));
vi.mock("@/lib/api", () => ({ apiFetch: fixture.apiFetch }));
vi.mock("@/lib/reading-api", () => ({
  rawMaterialUrl: () => "/api/reading/materials/book/raw",
  renderMaterialUrl: () => "/api/reading/materials/book/render",
  getReadingPosition: async () => ({ locator: 1 }),
  saveReadingPosition: vi.fn(async () => undefined),
}));

import { EpubDocumentView } from "@/components/reading/EpubDocumentView";

let publisherParagraph: HTMLParagraphElement | null = null;
let themeStyle: HTMLStyleElement | null = null;

beforeEach(() => {
  fixture.rendition.currentLocation.mockReturnValue({
    start: { cfi: "epubcfi(/6/2)" },
  });
  fixture.rendition.themes.registerCss.mockReset();
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 900,
    bottom: 600,
    width: 900,
    height: 600,
    toJSON: () => ({}),
  });
});

afterEach(() => {
  publisherParagraph?.remove();
  themeStyle?.remove();
  publisherParagraph = null;
  themeStyle = null;
});

it("opens EPUB in single-page mode and keeps the CFI when switching spreads", async () => {
  render(
    <EpubDocumentView
      materialId="book"
      unitCount={1}
      unitRefs={[]}
      annotations={[]}
      jump={null}
      onSelection={() => undefined}
    />,
  );

  await waitFor(() =>
    expect(fixture.renderTo).toHaveBeenCalledWith(
      expect.any(Element),
      expect.objectContaining({ spread: "none" }),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Switch to two-page spread" }));

  await waitFor(() => expect(fixture.rendition.spread).toHaveBeenCalledWith("auto"));
  await waitFor(() =>
    expect(fixture.rendition.resize).toHaveBeenCalledWith(900, 600),
  );
  expect(fixture.rendition.display).toHaveBeenCalledWith("epubcfi(/6/2)");
  expect(JSON.parse(localStorage.getItem("dt.reader.textPreferences") || "{}"))
    .toMatchObject({ spreadMode: "auto" });
});

it("overrides a publisher's explicit paragraph and span ink and font", async () => {
  publisherParagraph = document.createElement("p");
  publisherParagraph.style.cssText =
    "font-family: monospace; font-size: 11px; color: #000";
  publisherParagraph.innerHTML =
    '<span style="font-family: monospace; font-size: 11px; color: #000">Publisher text</span>';
  document.body.appendChild(publisherParagraph);
  themeStyle = document.createElement("style");
  document.head.appendChild(themeStyle);
  fixture.rendition.themes.registerCss.mockImplementation((_name, css) => {
    themeStyle!.textContent = css;
  });
  localStorage.setItem(
    "dt.reader.textPreferences",
    JSON.stringify({ fontSize: 23, serif: false, readerTheme: "night", spreadMode: "auto" }),
  );
  render(
    <EpubDocumentView
      materialId="book"
      unitCount={1}
      unitRefs={[]}
      annotations={[]}
      jump={null}
      onSelection={() => undefined}
    />,
  );

  await waitFor(() =>
    expect(fixture.renderTo).toHaveBeenCalledWith(
      expect.any(Element),
      expect.objectContaining({ spread: "auto" }),
    ),
  );
  const publisherSpan = publisherParagraph.querySelector("span")!;
  await waitFor(() =>
    expect(getComputedStyle(publisherSpan).color).toBe("rgb(232, 229, 223)"),
  );
  expect(getComputedStyle(publisherParagraph).fontFamily).toContain("ui-sans-serif");
  expect(getComputedStyle(publisherSpan).fontFamily).toContain("ui-sans-serif");
  expect(getComputedStyle(publisherSpan).fontSize).toBe("23px");
  expect(fixture.rendition.themes.fontSize).toHaveBeenCalledWith("23px");
  fireEvent.click(screen.getByRole("button", { name: "Reset reading display" }));
  await waitFor(() =>
    expect(getComputedStyle(publisherSpan).color).toBe("rgb(0, 0, 0)"),
  );
  expect(JSON.parse(localStorage.getItem("dt.reader.textPreferences") || "{}"))
    .toMatchObject({ fontSize: 17, readerTheme: "auto", spreadMode: "none" });
});

it("drops a previous book's pending CFI before the next book relayout", async () => {
  const onSelection = () => undefined;
  const props = {
    unitCount: 1,
    unitRefs: [],
    annotations: [],
    jump: null,
    onSelection,
  };
  fixture.rendition.currentLocation.mockReturnValue({
    start: { cfi: "epubcfi(/6/old-book)" },
  });
  const { rerender } = render(
    <EpubDocumentView materialId="old-book" {...props} />,
  );
  await waitFor(() => expect(fixture.renderTo).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Switch to two-page spread" }));
  await waitFor(() => expect(fixture.rendition.spread).toHaveBeenCalledWith("auto"));
  const oldCfiDisplays = fixture.rendition.display.mock.calls.filter(
    ([cfi]) => cfi === "epubcfi(/6/old-book)",
  ).length;

  fixture.rendition.currentLocation.mockReturnValue({
    start: { cfi: "epubcfi(/6/new-book)" },
  });
  rerender(<EpubDocumentView materialId="new-book" {...props} />);
  await waitFor(() => expect(fixture.renderTo).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(fixture.rendition.display).toHaveBeenLastCalledWith(
      "epubcfi(/6/new-book)",
    ),
  );
  expect(
    fixture.rendition.display.mock.calls.filter(
      ([cfi]) => cfi === "epubcfi(/6/old-book)",
    ),
  ).toHaveLength(oldCfiDisplays);
});
