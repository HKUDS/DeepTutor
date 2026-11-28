import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { AddMaterialsDialog } from "@/components/reading/library/AddMaterialsDialog";

const mock = vi.hoisted(() => ({
  addMaterial: vi.fn(),
  checkDuplicates: vi.fn(),
  createWorkspace: vi.fn(),
  importUrls: vi.fn(),
  listLibrary: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/components/watching/WatchingBrowser", () => ({
  WatchingBrowser: ({ onSelectUrl, onDismiss }: {
    onSelectUrl?(url: string): void;
    onDismiss(): void;
  }) => (
    <button
      type="button"
      onClick={() => {
        onSelectUrl?.("https://youtu.be/abc123xyz00");
        onDismiss();
      }}
    >
      Select video
    </button>
  ),
}));

vi.mock("@/lib/reading-api", () => ({
  uploadMaterial: vi.fn(),
}));

vi.mock("@/lib/reading-workspace-api", () => ({
  addReadingWorkspaceMaterial: mock.addMaterial,
  checkReadingDuplicates: mock.checkDuplicates,
  createReadingWorkspace: mock.createWorkspace,
  importReadingUrls: mock.importUrls,
  listReadingLibraryMaterials: mock.listLibrary,
  readingContentId: vi.fn(),
}));

// jsdom doesn't implement the native dialog methods. Chromium covers actual
// focus handling and Escape in the UI audit.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
    this.dispatchEvent(new Event("close"));
  };
});
afterAll(() => {
  Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
  Reflect.deleteProperty(HTMLDialogElement.prototype, "close");
});

beforeEach(() => {
  vi.clearAllMocks();
  mock.checkDuplicates.mockResolvedValue([]);
  mock.importUrls.mockResolvedValue({
    workspace: { workspace_id: "workspace-1" },
  });
});

describe("Reading Add Materials Invidious entry", () => {
  it("imports a selected video through Reading instead of the Watching route", async () => {
    const onDone = vi.fn();
    render(
      <AddMaterialsDialog
        mode="add"
        workspaceId="workspace-1"
        onClose={vi.fn()}
        onDone={onDone}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Browse Invidious" }));
    fireEvent.click(screen.getByRole("button", { name: "Select video" }));
    await waitFor(() =>
      expect(mock.importUrls).toHaveBeenCalledWith({
        urls: ["https://youtu.be/abc123xyz00"],
        workspace_id: "workspace-1",
      }),
    );
    await waitFor(() =>
      expect(onDone).toHaveBeenCalledWith({
        workspace: { workspace_id: "workspace-1" },
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Select video" }),
      ).toBeNull(),
    );
    expect(mock.addMaterial).not.toHaveBeenCalled();
  });
});
