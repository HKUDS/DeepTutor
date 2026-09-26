import {
  act,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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

// The workspace provider asks who the learner is; an adult reader is the
// case under test, so there is no learner policy to find.
vi.mock("@/lib/auth", () => ({
  fetchAuthStatus: vi.fn(async () => null),
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

const { READER_ASK_EVENT, ReaderPane } = await import(
  "@/components/reading/ReaderPane"
);
const { ReadingActionsProvider } = await import(
  "@/components/reading/ReadingActionsProvider"
);

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

  it("keeps secondary reading tools behind the more menu", async () => {
    const user = userEvent.setup();
    render(
      <ReaderPane
        onClose={() => undefined}
        onToggleBookmark={() => undefined}
      />,
    );

    const more = await screen.findByRole("button", { name: "More" });
    // At every width now, not only on phones: history, auto-jump and export
    // are settings and once-a-session actions, not toolbar buttons.
    expect(more.className).not.toContain("md:hidden");
    expect(
      screen.queryByRole("button", { name: /Export annotated file/ }),
    ).not.toBeInTheDocument();
    expect(more).toHaveAttribute("aria-haspopup", "menu");
    expect(
      screen.getByRole("button", { name: /Bookmark this page/ }),
    ).toBeVisible();

    await user.click(more);
    const menu = screen.getByRole("menu", { name: "More" });
    const autoJump = within(menu).getByRole("menuitemcheckbox", {
      name: /Auto-jump on/,
    });
    expect(autoJump.getAttribute("aria-checked")).toBe("true");
    expect(autoJump).toHaveFocus();

    await user.click(autoJump);
    expect(
      within(menu).getByRole("menuitemcheckbox", { name: /Auto-jump off/ }),
    ).toHaveAttribute("aria-checked", "false");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu", { name: "More" })).not.toBeInTheDocument();
    expect(more).toHaveFocus();
  });

  /**
   * Inside a workspace the selection's verbs are on the popover, and they
   * are messages in the reading conversation: the popover hands the passage
   * and the words to the workspace instead of running an extension with its
   * own model call and its own result card.
   */
  it("sends selection actions to the reading conversation", async () => {
    const user = userEvent.setup();
    const asks: Array<Record<string, unknown>> = [];
    const onAsk = (event: Event) =>
      asks.push((event as CustomEvent<Record<string, unknown>>).detail);
    window.addEventListener(READER_ASK_EVENT, onAsk);
    render(
      <ReadingActionsProvider materialId="m1" locator={1}>
        <ReaderPane onClose={() => undefined} />
      </ReadingActionsProvider>,
    );

    await waitFor(() => expect(view.select).not.toBeNull());
    act(() =>
      view.select?.({
        locator: 4,
        quote: "the slope of the 3 line",
        // What the page view recovers once the margin line number is gone.
        text: "the slope of the line",
        rects: [],
        anchor: { x: 100, y: 200 },
      }),
    );

    const popover = await screen.findByRole("dialog", {
      name: "Annotate selection",
    });
    const translate = await within(popover).findByRole("button", {
      name: "Translate this passage into Chinese",
    });
    expect(translate).toHaveTextContent("Translate");
    expect(
      within(popover).getByRole("button", { name: "Ask about this" }),
    ).toBeVisible();
    // The extension the prompt replaced is not offered a second time.
    expect(
      within(popover).queryByRole("button", { name: "Translate to Chinese" }),
    ).not.toBeInTheDocument();
    await user.click(translate);

    window.removeEventListener(READER_ASK_EVENT, onAsk);
    expect(asks).toEqual([
      expect.objectContaining({
        quote: "the slope of the line",
        locator: 4,
        prompt: "Translate this passage into Chinese",
      }),
    ]);
    expect(api.runReadingExtension).not.toHaveBeenCalled();
    // The popover closes once the question is on its way.
    expect(
      screen.queryByRole("dialog", { name: "Annotate selection" }),
    ).not.toBeInTheDocument();
  });
});
