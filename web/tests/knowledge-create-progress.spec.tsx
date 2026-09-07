import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";
import { useKnowledgeProgress } from "@/hooks/useKnowledgeProgress";

const fixture = vi.hoisted(() => ({
  t: (key: string) => key,
  create: vi.fn(),
}));

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: fixture.t }) }));
vi.mock("@/features/knowledge/api/catalog", async (original) => ({
  ...(await original<typeof import("@/features/knowledge/api/catalog")>()),
  createKnowledgeBase: fixture.create,
  listKnowledgeBases: async () => [],
  listRagProviders: async () => [],
  getKnowledgeUploadPolicy: async () => {
    throw new Error("use default upload policy");
  },
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
  fixture.create.mockReset().mockResolvedValue({ task_id: null, files: [] });
  Socket.instances = [];
  Stream.instances = [];
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("EventSource", Stream);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("completes empty creation without opening a progress socket or task stream", async () => {
  const { result } = renderHook(() => useKnowledgeBases());
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => {
    await result.current.createKb({
      name: "empty",
      provider: "llamaindex",
      files: [],
    });
  });
  expect(Socket.instances).toHaveLength(0);
  expect(Stream.instances).toHaveLength(0);
  expect(result.current.error).toBeNull();
});

it("tracks creation when the server accepts an indexing task", async () => {
  fixture.create.mockResolvedValue({ task_id: "index-task", files: ["text.txt"] });
  const { result } = renderHook(() => useKnowledgeBases());
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => {
    await result.current.createKb({
      name: "papers",
      provider: "llamaindex",
      files: [new File(["hello"], "text.txt")],
    });
  });
  expect(Socket.instances).toHaveLength(1);
  expect(Socket.instances[0].url).toContain("/papers/progress?task_id=index-task");
  expect(Stream.instances).toHaveLength(1);
  expect(Stream.instances[0].url).toContain("/tasks/index-task/stream");
  expect(result.current.tasksByKb.papers).toMatchObject({
    taskId: "index-task",
    executing: true,
  });
});

it("subscribes without a task ID and tolerates opening a removed target", () => {
  const { result } = renderHook(() => useKnowledgeProgress());
  act(() => result.current.subscribeWs("kb"));
  const socket = Socket.instances[0];
  expect(socket.url).toContain("/kb/progress");
  expect(socket.url).not.toContain("task_id");
  expect(() => socket.onopen?.()).not.toThrow();
  act(() => result.current.cleanupKb("kb"));
  expect(socket.close).toHaveBeenCalledOnce();
  expect(() => socket.onopen?.()).not.toThrow();
});
