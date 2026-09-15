import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import KbLinkedFoldersSection from "@/components/knowledge/KbLinkedFoldersSection";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  link: vi.fn(),
  unlink: vi.fn(),
  sync: vi.fn(),
  startTask: vi.fn(),
}));

vi.mock("@/features/knowledge/api/sources", () => ({
  listLinkedFolders: api.list,
  linkFolder: api.link,
  unlinkFolder: api.unlink,
  syncLinkedFolder: api.sync,
}));

vi.mock("@/hooks/useKnowledgeProgress", () => ({
  useKnowledgeProgress: () => ({
    startTask: api.startTask,
    tasksByKb: {},
    progressByKb: {},
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const folder = {
  id: "folder-1",
  path: "/tmp/research-notes",
  added_at: "2026-09-09T12:00:00",
  file_count: 4,
  last_sync: null,
};

beforeEach(() => {
  api.list.mockReset().mockResolvedValue([]);
  api.link.mockReset().mockResolvedValue(folder);
  api.unlink.mockReset().mockResolvedValue(undefined);
  api.sync.mockReset().mockResolvedValue({
    message: "No new or modified files to sync",
    file_count: 0,
  });
  api.startTask.mockReset();
});

afterEach(cleanup);

it("links a folder and refreshes the list", async () => {
  api.list.mockResolvedValueOnce([]).mockResolvedValueOnce([folder]);

  render(<KbLinkedFoldersSection kbName="kb" />);
  fireEvent.click(await screen.findByRole("button", { name: "Link folder" }));
  fireEvent.change(screen.getByLabelText("Folder path"), {
    target: { value: "/tmp/research-notes" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^Link$/ }));

  await waitFor(() => expect(api.link).toHaveBeenCalledWith("kb", "/tmp/research-notes"));
  await waitFor(() => expect(screen.getByText("/tmp/research-notes")).toBeVisible());
  expect(screen.getByText("Folder linked.")).toBeVisible();
});

it("reports a completed no-op sync", async () => {
  api.list.mockResolvedValue([folder]);

  render(<KbLinkedFoldersSection kbName="kb" />);
  fireEvent.click(await screen.findByRole("button", { name: "Sync now" }));

  expect(await screen.findByText("No new or modified files to sync.")).toBeVisible();
  expect(api.sync).toHaveBeenCalledWith("kb", "folder-1");
});

it("shows the last successful sync time", async () => {
  api.list.mockResolvedValue([
    { ...folder, last_sync: "2026-09-09T12:00:00" },
  ]);

  render(<KbLinkedFoldersSection kbName="kb" />);

  expect(
    await screen.findByText((_, element) =>
      Boolean(element?.textContent?.startsWith("Last synced:")),
    ),
  ).toBeVisible();
});

it("unlinks a folder and refreshes the list", async () => {
  api.list.mockResolvedValue([folder]);

  render(<KbLinkedFoldersSection kbName="kb" />);
  fireEvent.click(await screen.findByRole("button", { name: "Unlink folder" }));

  await waitFor(() => expect(api.unlink).toHaveBeenCalledWith("kb", "folder-1"));
  expect(await screen.findByText("Folder unlinked.")).toBeVisible();
});

it("streams a changed-folder sync through the shared task hook", async () => {
  api.list.mockResolvedValue([folder]);
  api.sync.mockResolvedValue({
    message: "Syncing 2 files from linked folder",
    file_count: 2,
    task_id: "folder-task",
  });

  render(<KbLinkedFoldersSection kbName="kb" />);
  fireEvent.click(await screen.findByRole("button", { name: "Sync now" }));

  await waitFor(() =>
    expect(api.startTask).toHaveBeenCalledWith(
      expect.objectContaining({ kbName: "kb", taskId: "folder-task" }),
    ),
  );
});
