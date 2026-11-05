import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReadingWorkspacePage } from "@/components/reading/workspace/ReadingWorkspace";

/**
 * The production reading route is `ReadingWorkspacePage` — the only mount of
 * `ReaderPane` is here, and it passes `ownAnnotationList={false}`, so the
 * reader pane's own resizable annotation column never renders in production.
 * The outline the reader actually sees is `SourceNavigator`, and this spec
 * asserts on that component rather than on a mocked stand-in: a resizable
 * panel that only exists in the unmounted half of the product is exactly the
 * defect these tests exist to catch.
 *
 * `SourceNavigator` is deliberately NOT mocked here.
 */

vi.mock("next/navigation", () => ({
  useParams: () => ({ workspaceId: "reading-1" }),
  usePathname: () => "/learning/reading/reading-1",
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (value: string) => value }),
}));
vi.mock("@/features/chat/ChatStateAdapter", () => ({
  useChatStateAdapter: () => ({
    state: { isStreaming: false, sessionId: null },
    sendMessage: vi.fn(),
  }),
}));
vi.mock("@/components/reading/workspace/useReadingWorkspace", () => ({
  useReadingWorkspace: () => ({
    workspace: {
      workspace_id: "reading-1",
      title: "Collection",
      tabs: [],
      active_material_id: null,
    },
    setWorkspace: vi.fn(),
    conversations: [],
    setConversations: vi.fn(),
    loading: false,
    error: null,
    notice: null,
    setNotice: vi.fn(),
    material: null,
    annotations: [],
    activeTab: undefined,
    activeConversation: null,
    linkedSessionIds: [],
    activeLocator: 1,
    setActiveLocator: vi.fn(),
    transcript: [],
    organizedNotes: null,
    setOrganizedNotes: vi.fn(),
    refresh: vi.fn(),
    switchMaterial: vi.fn(),
    removeMaterial: vi.fn(),
    newConversation: vi.fn(),
    organizeNotes: vi.fn(),
    buildMasteryPath: vi.fn(),
    renameWorkspace: vi.fn(),
    reportViewport: vi.fn(),
    bookmarks: [],
    toggleBookmark: vi.fn(),
    removeBookmark: vi.fn(),
  }),
}));
vi.mock("@/components/reading/ReaderPane", () => ({
  ReaderPane: () => null,
  READER_ASK_EVENT: "dt:reader-ask",
}));
vi.mock("@/components/reading/ReadingActionsProvider", () => ({
  ReadingActionsProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));
vi.mock("@/components/reading/workspace/ReadingCompanion", () => ({
  ReadingCompanion: () => <div data-testid="reading-companion" />,
}));
vi.mock("@/components/reading/workspace/MediaReadingStage", () => ({
  MediaReadingStage: () => null,
}));
vi.mock("@/components/reading/library/AddMaterialsDialog", () => ({
  AddMaterialsDialog: () => null,
}));
vi.mock("@/components/reading/workspace/WorkspaceChrome", () => ({
  CompanionWelcome: () => null,
  EmptyWorkspace: () => null,
  MaterialFailure: () => null,
  MaterialProcessing: () => null,
  MenuItem: ({ label }: { label: string }) => <span>{label}</span>,
  iconForMaterial: () => () => null,
}));
vi.mock("@/components/reading/workspace/dialogs", () => ({
  ConversationLinkDialog: () => null,
  NotebookCaptureDialog: () => null,
  OrganizedNotesDialog: () => null,
  WorkspaceConfirmDialog: () => null,
  WorkspaceValueDialog: () => null,
}));

let observers: (() => void)[] = [];

/** Answer `matchMedia` from the pixel width, the way the browser would. */
function useViewport(width: number) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => {
      const min = query.match(/min-width:\s*(\d+)px/);
      const max = query.match(/max-width:\s*(\d+)px/);
      const matches = min
        ? width >= Number(min[1])
        : max
          ? width <= Number(max[1])
          : false;
      return {
        matches,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      };
    }),
  });
}

beforeEach(() => {
  observers = [];
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    () => 1280,
  );
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        observers.push(callback);
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "PointerEvent",
    class extends MouseEvent {
      pointerId: number;
      constructor(type: string, options: PointerEventInit) {
        super(type, options);
        this.pointerId = options.pointerId ?? 1;
      }
    },
  );
  Object.defineProperties(HTMLElement.prototype, {
    setPointerCapture: { configurable: true, value: vi.fn() },
    hasPointerCapture: { configurable: true, value: vi.fn(() => true) },
    releasePointerCapture: { configurable: true, value: vi.fn() },
  });
});

afterEach(() => vi.unstubAllGlobals());

/** Open the outline and let the measured grid settle. */
async function openOutline() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Expand contents" }));
  await waitFor(() =>
    expect(
      document.querySelector('[data-reading-workspace] aside.dt-reading-navigator'),
    ).toBeTruthy(),
  );
  await act(async () => observers.at(-1)?.());
  await waitFor(() =>
    expect(document.querySelector(".relative.grid")).toBeTruthy(),
  );
}

function gridColumns(): string {
  const grid = document.querySelector(".relative.grid") as HTMLElement | null;
  return grid?.style.gridTemplateColumns ?? "";
}

describe("the production reading route resizes its real outline panel", () => {
  it("sizes the SourceNavigator column at lg, where it docks and the companion does not", async () => {
    useViewport(1100);
    render(<ReadingWorkspacePage />);
    await openOutline();

    // The outline the reader sees owns a column, and it is resizable.
    const handle = screen.getByRole("separator", {
      name: "Resize contents navigator",
    });
    expect(handle).toHaveAttribute("aria-valuenow", "210");
    expect(gridColumns()).toBe("210px 5px minmax(0,1fr)");

    // The companion is still a sheet at this width, so it must not reserve a
    // track and must not offer a handle that would drag nothing.
    expect(
      screen.queryByRole("separator", { name: "Resize reading companion" }),
    ).not.toBeInTheDocument();

    // Keyboard resize, the affordance the separator has always supported.
    fireEvent.keyDown(handle, { key: "End" });
    expect(handle).toHaveAttribute("aria-valuenow", "400");
    expect(gridColumns()).toBe("400px 5px minmax(0,1fr)");
    expect(localStorage.getItem("dt.reader.navigatorWidth")).toBe("400");

    // And a pointer drag moves the same single width state.
    fireEvent.pointerDown(handle, { button: 0, pointerId: 4, clientX: 400 });
    fireEvent.pointerMove(handle, { pointerId: 4, clientX: 320 });
    fireEvent.pointerUp(handle, { pointerId: 4 });
    expect(handle).toHaveAttribute("aria-valuenow", "320");
    expect(gridColumns()).toBe("320px 5px minmax(0,1fr)");
    expect(localStorage.getItem("dt.reader.navigatorWidth")).toBe("320");
  });

  it("keeps the remembered width when the route is reopened", async () => {
    localStorage.setItem("dt.reader.navigatorWidth", "360");
    useViewport(1100);
    render(<ReadingWorkspacePage />);
    await openOutline();

    expect(
      screen.getByRole("separator", { name: "Resize contents navigator" }),
    ).toHaveAttribute("aria-valuenow", "360");
    expect(gridColumns()).toBe("360px 5px minmax(0,1fr)");
  });

  it("leaves the outline a drawer with no resize seam below lg", async () => {
    useViewport(900);
    render(<ReadingWorkspacePage />);
    await openOutline();

    // Below `lg` the navigator is an overlay, not a column: it keeps the fixed
    // `w-[min(300px,88vw)]` the sheet always had, and no separator is drawn.
    expect(
      screen.queryByRole("separator", { name: "Resize contents navigator" }),
    ).not.toBeInTheDocument();
    expect(gridColumns()).toBe("");
    expect(
      document
        .querySelector("aside.dt-reading-navigator")
        ?.className.includes("w-[min(300px,88vw)]"),
    ).toBe(true);
  });

  it("resizes both columns independently at xl", async () => {
    useViewport(1400);
    render(<ReadingWorkspacePage />);
    await openOutline();

    const nav = screen.getByRole("separator", {
      name: "Resize contents navigator",
    });
    const companion = screen.getByRole("separator", {
      name: "Resize reading companion",
    });
    expect(gridColumns()).toBe("210px 5px minmax(0,1fr) 5px 380px");

    fireEvent.keyDown(nav, { key: "End" });
    expect(nav).toHaveAttribute("aria-valuenow", "400");
    // The companion keeps its width: one drag may use free reader space, but
    // it never displaces the other panel.
    expect(companion).toHaveAttribute("aria-valuenow", "380");
    expect(gridColumns()).toBe("400px 5px minmax(0,1fr) 5px 380px");
  });
});
