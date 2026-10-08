import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ArrowRight } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

const api = vi.hoisted(() => ({
  fetchExport: vi.fn(),
  getMaterial: vi.fn(async () => null),
  getReadingPosition: vi.fn(async () => ({ locator: 1, source_anchor: "" })),
  saveReadingPosition: vi.fn(),
}));

/** The document view is stubbed down to "report selections upward". */
const view = vi.hoisted(() => ({
  select: null as null | ((payload: unknown) => void),
}));

vi.mock("@/lib/reading-api", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...api,
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
  // The history store only accepts hash-shaped material ids; a made-up "m1"
  // would be dropped and every history assertion below would vacuously pass.
  material_id: "0123456789abcdef",
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
const { WorkspaceMenu } = await import(
  "@/components/reading/workspace/WorkspaceMenu"
);

/**
 * #916, header half: below 768px the reader's top bar converges to back,
 * title + chapter, bookmark and ⋯. jsdom lays nothing out, so "cannot
 * overflow horizontally" is asserted the only honest way available — every
 * child of the row either truncates inside its own box or is `shrink-0`,
 * and the controls that would crowd the row are display:none below `md`.
 */
describe("reader header below 768px", () => {
  it("converges to back, title + chapter, bookmark and more without an overflow path", async () => {
    const { container } = render(
      <ReaderPane
        onClose={() => undefined}
        onToggleBookmark={() => undefined}
      />,
    );

    // The flexible middle: title and chapter indicator each truncate inside
    // their own share of the row.
    const title = await screen.findByText("Understanding Deep Learning");
    expect(title.className).toContain("min-w-0");
    expect(title.className).toContain("flex-1");
    expect(title.className).toContain("truncate");

    const position = screen.getByText(/1\s*\/\s*10/);
    expect(position.className).toContain("min-w-0");
    expect(position.className).toContain("truncate");
    expect(position.className).toContain("max-w-[45%]");
    // Desktop keeps the indicator unconstrained — the bound is mobile-only.
    expect(position.className).toContain("md:max-w-none");
    expect(position.className).toContain("md:shrink-0");

    // The four controls that stay: back, bookmark, more — all fixed-width.
    for (const name of ["Back", /Bookmark this page/, "More"]) {
      const button = screen.getByRole("button", { name });
      expect(button.className).toContain("shrink-0");
      expect(button.className).not.toContain("hidden");
    }

    // What left the mobile bar: forward (into the ⋯ menu) and the file icon.
    const forward = screen.getByRole("button", { name: "Forward" });
    expect(forward.className).toContain("hidden");
    expect(forward.className).toContain("md:inline-flex");
    // SVG className is not a string; read the attribute instead.
    const fileIconClass =
      container.querySelector(".lucide-file-text")?.getAttribute("class") ??
      "";
    expect(fileIconClass).toContain("hidden");
    expect(fileIconClass).toContain("md:block");
  });

  it("keeps forward reachable from the more menu on a phone", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ReaderPane onClose={() => undefined} externalJump={null} />,
    );

    // Two explicit jumps give the history three entries; the pane sits on the
    // last one, so forward is disabled until the reader steps back.
    const jump = (locator: number, nonce: number) =>
      rerender(
        <ReaderPane
          onClose={() => undefined}
          externalJump={{ locator, nonce }}
        />,
      );
    jump(5, 1);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Back" })).toBeEnabled(),
    );
    jump(6, 2);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled(),
    );

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("button", { name: "Forward" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "More" }));
    const menu = screen.getByRole("menu", { name: "More" });
    const menuForward = within(menu).getByRole("menuitem", {
      name: "Forward",
    });
    // Mobile-only: the menu does not offer forward twice on desktop.
    expect(menuForward.className).toContain("md:hidden");
    await user.click(menuForward);

    expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();
  });

  it("marks workspace-hosted mobile-only items below md only", async () => {
    const user = userEvent.setup();
    render(
      <WorkspaceMenu
        collection={[]}
        sections={{
          material: [
            {
              key: "forward",
              icon: ArrowRight,
              label: "Forward",
              onSelect: () => undefined,
              mobileOnly: true,
            },
          ],
        }}
      />,
    );
    await user.click(screen.getByRole("button", { name: "More" }));
    // Plain workspace menu actions carry no ARIA role of their own (only
    // the checkbox toggles do) — the button is the queryable surface.
    const item = screen.getByRole("button", { name: "Forward" });
    expect(item.className).toContain("md:hidden");
  });
});
