import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import KbLinkedFoldersSection from "@/components/knowledge/KbLinkedFoldersSection";
import type { KnowledgeBase } from "@/lib/knowledge-helpers";

const fixture = vi.hoisted(() => ({
  t: (key: string, values?: Record<string, string | number>) =>
    key.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(values?.[name] ?? `{{${name}}}`)),
  list: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: fixture.t }),
}));

vi.mock("@/features/knowledge/api/folders", () => ({
  listLinkedFolders: fixture.list,
}));

const kb: KnowledgeBase = {
  name: "papers",
  status: "ready",
  statistics: { raw_documents: 1 },
};

const folder = {
  id: "folder-1",
  path: "/notes",
  added_at: "2026-09-09T10:00:00",
  file_count: 0,
  last_sync: null,
};

beforeEach(() => {
  fixture.list.mockReset().mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

it("links a folder without automatically starting its first sync", async () => {
  const onLinkFolder = vi.fn().mockResolvedValue(undefined);
  const onUnlinkFolder = vi.fn().mockResolvedValue(undefined);
  const onSyncFolder = vi.fn().mockResolvedValue({
    message: "No new or modified files to sync",
    files: [],
    new_files: 0,
    modified_files: 0,
    file_count: 0,
    task_id: null,
  });
  fixture.list.mockResolvedValueOnce([]).mockResolvedValue([folder]);

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={onLinkFolder}
      onUnlinkFolder={onUnlinkFolder}
      onSyncFolder={onSyncFolder}
    />,
  );

  await waitFor(() => expect(fixture.list).toHaveBeenCalled());
  fireEvent.click(screen.getAllByRole("button", { name: "Link folder" })[0]);
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Folder path"), {
    target: { value: "/notes" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Link folder" }));

  await waitFor(() => expect(onLinkFolder).toHaveBeenCalledWith("/notes"));
  expect(onSyncFolder).not.toHaveBeenCalled();
  expect(await screen.findByText("/notes")).toBeInTheDocument();
  expect(screen.getByText(/Never synced/)).toBeInTheDocument();
});

it("shows the no-change result after a manual sync", async () => {
  fixture.list.mockResolvedValue([folder]);
  const onSyncFolder = vi.fn().mockResolvedValue({
    message: "No new or modified files to sync",
    files: [],
    new_files: 0,
    modified_files: 0,
    file_count: 0,
    task_id: null,
  });

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={onSyncFolder}
    />,
  );

  await waitFor(() => expect(screen.getByText("/notes")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

  await waitFor(() =>
    expect(onSyncFolder).toHaveBeenCalledWith("folder-1"),
  );
  expect(
    await screen.findByText("No new or modified files to sync"),
  ).toBeInTheDocument();
});

it("shows queued sync counts for new and modified files", async () => {
  fixture.list.mockResolvedValue([folder]);
  const onSyncFolder = vi.fn().mockResolvedValue({
    message: "Syncing 3 files from linked folder",
    folder_path: "/notes",
    files: ["/notes/a.md", "/notes/b.md", "/notes/c.md"],
    new_files: 2,
    modified_files: 1,
    file_count: 3,
    task_id: "sync-task",
  });

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={onSyncFolder}
    />,
  );

  await waitFor(() => expect(screen.getByText("/notes")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

  expect(
    await screen.findByText("Queued 3 files for indexing. 2 new, 1 modified."),
  ).toBeInTheDocument();
});

it("shows a retry action when the linked-folder list fails to load", async () => {
  fixture.list
    .mockRejectedValueOnce(new Error("Folder service unavailable"))
    .mockResolvedValueOnce([]);

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={vi.fn()}
    />,
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Folder service unavailable",
  );
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  await waitFor(() => expect(fixture.list).toHaveBeenCalledTimes(2));
  expect(
    screen.getByText(/No linked folders yet/),
  ).toBeInTheDocument();
});

it("validates the link modal and confirms unlinking", async () => {
  fixture.list.mockResolvedValue([folder]);
  const onLinkFolder = vi.fn().mockResolvedValue(undefined);
  const onUnlinkFolder = vi.fn().mockResolvedValue(undefined);
  const confirm = vi.spyOn(window, "confirm");

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={onLinkFolder}
      onUnlinkFolder={onUnlinkFolder}
      onSyncFolder={vi.fn()}
    />,
  );

  await waitFor(() => expect(screen.getByText("/notes")).toBeInTheDocument());
  fireEvent.click(screen.getAllByRole("button", { name: "Link folder" })[0]);
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Link folder" }));
  expect(onLinkFolder).not.toHaveBeenCalled();
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Folder path is required.",
  );

  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  confirm.mockReturnValueOnce(false);
  fireEvent.click(screen.getByRole("button", { name: "Unlink /notes" }));
  expect(onUnlinkFolder).not.toHaveBeenCalled();

  confirm.mockReturnValueOnce(true);
  fireEvent.click(screen.getByRole("button", { name: "Unlink /notes" }));
  await waitFor(() => expect(onUnlinkFolder).toHaveBeenCalledWith("folder-1"));
  expect(screen.queryByText("/notes")).not.toBeInTheDocument();
});

it("keeps linked-folder controls disabled for a read-only knowledge base", async () => {
  fixture.list.mockResolvedValue([folder]);

  render(
    <KbLinkedFoldersSection
      kb={{ ...kb, read_only: true }}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={vi.fn()}
    />,
  );

  await waitFor(() => expect(screen.getByText("/notes")).toBeInTheDocument());
  expect(
    screen.getByText(
      "This knowledge base is read-only. Linked folders can be viewed but not changed.",
    ),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Link folder" })[0]).toBeDisabled();
  expect(screen.getByRole("button", { name: "Sync now" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Unlink /notes" })).toBeDisabled();
});
