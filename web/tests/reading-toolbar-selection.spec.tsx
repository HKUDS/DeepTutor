import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

const api = vi.hoisted(() => ({
  runReadingExtension: vi.fn(
    async (
      _materialId: string,
      _extensionId: string,
      _actionId: string,
      _body: { locator: number; selection: string; locale: string },
    ) => ({
      type: "card",
      title: "Translation",
      message: "",
      payload: { translation: "斜率" },
    }),
  ),
  listReadingExtensions: vi.fn(async () => [
    {
      id: "translation",
      version: "1.0.0",
      name: "Translation",
      actions: [
        {
          id: "translate_zh",
          label: "Translate to Chinese",
          requires: ["selection"],
        },
      ],
      result_types: ["card"],
    },
  ]),
}));

/** The document view is stubbed down to "report this selection upward". */
const view = vi.hoisted(() => ({
  select: null as null | ((payload: unknown) => void),
}));

vi.mock("@/lib/reading-api", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...api,
  fetchExport: vi.fn(),
  getMaterial: vi.fn(async () => null),
  getReadingPosition: vi.fn(async () => ({ locator: 1, source_anchor: "" })),
  saveReadingPosition: vi.fn(),
}));

vi.mock("@/components/reading/PdfDocumentView", () => ({
  PdfDocumentView: ({
    onSelection,
  }: {
    onSelection: (payload: unknown) => void;
  }) => {
    view.select = onSelection;
    return <div data-testid="doc" />;
  },
}));

vi.mock("@/components/reading/EpubDocumentView", () => ({
  EpubDocumentView: () => null,
}));

vi.mock("@/components/reading/TextUnitView", () => ({
  TextUnitView: () => null,
  unitLabel: () => "page",
}));

vi.mock("@/components/reading/AnnotationList", () => ({
  AnnotationList: () => null,
}));

const material = {
  material_id: "m1",
  title: "Understanding Deep Learning",
  filename: "udl.pdf",
  unit: "page",
  mime: "application/pdf",
  render_mode: "raw",
  has_raw_view: true,
  unit_count: 10,
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

const { ReaderPane } = await import("@/components/reading/ReaderPane");

describe("reading toolbar with a live selection", () => {
  beforeEach(() => {
    api.runReadingExtension.mockClear();
    view.select = null;
  });

  /**
   * The regression. `AnnotationPopover` dismisses itself on a document-level,
   * CAPTURE-phase pointerdown, and that used to clear the reader's selection.
   * Pressing a toolbar button therefore disabled it between `pointerdown` and
   * `click` — and a disabled control receives neither — so 翻译成中文 and the
   * three other selection-gated actions did nothing at all, silently.
   */
  it("runs a selection-gated action when the button is pressed", async () => {
    const user = userEvent.setup();
    render(<ReaderPane onClose={() => undefined} />);

    await waitFor(() => expect(view.select).not.toBeNull());
    act(() =>
      view.select?.({
        locator: 4,
        quote: "the slope of the line",
        rects: [],
        anchor: { x: 100, y: 200 },
      }),
    );

    const button = await screen.findByRole("button", {
      name: "Translate to Chinese",
    });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);

    await waitFor(() => expect(api.runReadingExtension).toHaveBeenCalled());
    const call = api.runReadingExtension.mock.calls[0];
    expect(call).toBeDefined();
    const [materialId, extensionId, actionId, body] = call;
    expect(materialId).toBe("m1");
    expect(extensionId).toBe("translation");
    expect(actionId).toBe("translate_zh");
    expect(body.selection).toBe("the slope of the line");
    // The selection's own unit, not the scroll-derived viewport locator: the
    // server verifies the quote against the text of the unit it is told about
    // and 400s when they disagree.
    expect(body.locator).toBe(4);
  });
});
