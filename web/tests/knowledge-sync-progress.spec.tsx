import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";

const fixture = vi.hoisted(() => ({
  t: (key: string) => key,
  sync: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: fixture.t }),
}));

vi.mock("@/features/knowledge/api/catalog", async (original) => ({
  ...(await original<typeof import("@/features/knowledge/api/catalog")>()),
  listKnowledgeBases: async () => [
    {
      name: "papers",
      status: "ready",
      statistics: { raw_documents: 1 },
    },
  ],
  listRagProviders: async () => [],
  getKnowledgeUploadPolicy: async () => {
    throw new Error("use default upload policy");
  },
}));

vi.mock("@/features/knowledge/api/folders", () => ({
  linkFolder: vi.fn(),
  listLinkedFolders: vi.fn(),
  syncLinkedFolder: fixture.sync,
  unlinkFolder: vi.fn(),
}));

class Socket {
  static instances: Socket[] = [];
  onopen?: () => void;
  close = vi.fn();
  constructor(public url: string) {
    Socket.instances.push(this);
  }
}

class Stream {
  static instances: Stream[] = [];
  addEventListener = vi.fn();
  close = vi.fn();
  constructor(public url: string) {
    Stream.instances.push(this);
  }
}

beforeEach(() => {
  fixture.sync.mockReset().mockResolvedValue({
    message: "Syncing 1 files from linked folder",
    folder_path: "/notes",
    files: [],
    new_files: 1,
    modified_files: 0,
    file_count: 1,
    task_id: "sync-task",
  });
  Socket.instances = [];
  Stream.instances = [];
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("EventSource", Stream);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("tracks linked-folder syncs as their own progress task", async () => {
  const { result } = renderHook(() => useKnowledgeBases());
  await waitFor(() => expect(result.current.loading).toBe(false));

  await act(async () => {
    await result.current.syncLinkedFolder("papers", "folder-1");
  });

  expect(fixture.sync).toHaveBeenCalledWith("papers", "folder-1");
  expect(result.current.tasksByKb.papers).toMatchObject({
    taskId: "sync-task",
    kind: "sync",
    executing: true,
  });
  expect(Socket.instances).toHaveLength(1);
  expect(Socket.instances[0].url).toContain(
    "/papers/progress?task_id=sync-task",
  );
  expect(Stream.instances).toHaveLength(1);
  expect(Stream.instances[0].url).toContain("/tasks/sync-task/stream");
});
