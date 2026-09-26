import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";
import { useKnowledgeProgress } from "@/hooks/useKnowledgeProgress";

const fixture = vi.hoisted(() => ({
  t: (key: string) => key,
  create: vi.fn(),
  list: vi.fn(),
}));

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: fixture.t }) }));
vi.mock("@/features/knowledge/api/catalog", async (original) => ({
  ...(await original<typeof import("@/features/knowledge/api/catalog")>()),
  createKnowledgeBase: fixture.create,
  listKnowledgeBases: fixture.list,
  listRagProviders: async () => [],
  getKnowledgeUploadPolicy: async () => {
    throw new Error("use default upload policy");
  },
}));

class Socket {
  static instances: Socket[] = [];
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  close = vi.fn();
  constructor(public url: string) {
    Socket.instances.push(this);
  }
}

class Stream {
  static instances: Stream[] = [];
  listeners = new Map<string, (event: { data: string }) => void>();
  addEventListener = vi.fn(
    (type: string, listener: (event: { data: string }) => void) =>
      this.listeners.set(type, listener),
  );
  emit(type: string, payload: unknown) {
    this.listeners.get(type)?.({ data: JSON.stringify(payload) });
  }
  close = vi.fn();
  constructor(public url: string) {
    Stream.instances.push(this);
  }
}

beforeEach(() => {
  fixture.create.mockReset().mockResolvedValue({ task_id: null, files: [] });
  fixture.list.mockReset().mockResolvedValue([]);
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
  fixture.create.mockResolvedValue({
    task_id: "index-task",
    files: ["text.txt"],
  });
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
  expect(Socket.instances[0].url).toContain(
    "/papers/progress?task_id=index-task",
  );
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

it("keeps one log line when process and structured progress interleave", () => {
  const { result } = renderHook(() => useKnowledgeProgress());
  act(() =>
    result.current.resumeTask("papers", {
      task_id: "kb_reindex_1478",
      stage: "processing_documents",
      message: "Embedding batches: 1/5",
    }),
  );
  const stream = Stream.instances[0];
  act(() => {
    stream.emit("process_log", { message: "Embedding batches: 1/5" });
    stream.emit("progress", {
      task_id: "kb_reindex_1478",
      stage: "processing_documents",
      message: "Embedding batches: 1/5",
    });
    stream.emit("process_log", { message: "Embedding batches: 1/5" });
  });
  expect(result.current.tasksByKb.papers.logs).toEqual(["Embedding batches: 1/5"]);
});

it("restores the log stream when opening a processing KB, without clearing logs on refresh", async () => {
  const kbId = "workspace:study:kb:papers";
  fixture.list.mockResolvedValue([
    {
      id: kbId,
      name: "papers",
      status: "processing",
      statistics: {},
      progress: {
        task_id: "kb_reindex_running",
        stage: "processing_documents",
        message: "Embedding batches: 2/5",
        progress_percent: 40,
      },
    },
  ]);
  const { result } = renderHook(() => useKnowledgeBases());
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(Stream.instances).toHaveLength(1);
  expect(Stream.instances[0].url).toContain("/tasks/kb_reindex_running/stream");
  expect(result.current.tasksByKb[kbId]).toMatchObject({
    kind: "reindex",
    executing: true,
  });
  act(() =>
    Stream.instances[0].emit("process_log", {
      message: "Restored backend detail",
    }),
  );
  expect(result.current.tasksByKb[kbId].logs).toContain(
    "Restored backend detail",
  );
  await act(async () => {
    await result.current.refresh({ force: true });
  });
  expect(Stream.instances).toHaveLength(1);
  expect(Socket.instances).toHaveLength(1);
  expect(result.current.tasksByKb[kbId].logs).toContain(
    "Restored backend detail",
  );
  act(() => Stream.instances[0].emit("complete", {}));
  await waitFor(() =>
    expect(result.current.tasksByKb[kbId].executing).toBe(false),
  );
  expect(Stream.instances).toHaveLength(1);
});

it("opens detailed logs when a legacy progress connection discovers its task ID", () => {
  const { result } = renderHook(() => useKnowledgeProgress());
  act(() => result.current.resumeTask("papers", { stage: "starting" }));
  expect(Stream.instances).toHaveLength(0);
  act(() =>
    Socket.instances[0].onmessage?.({
      data: JSON.stringify({
        type: "progress",
        data: {
          task_id: "kb_init_discovered",
          stage: "processing_documents",
          message: "Parsing document",
        },
      }),
    }),
  );
  expect(Stream.instances).toHaveLength(1);
  expect(result.current.tasksByKb.papers).toMatchObject({
    kind: "create",
    executing: true,
    logs: ["Parsing document"],
  });
});

it("ignores late events from a task replaced by a new processing run", () => {
  const { result } = renderHook(() => useKnowledgeProgress());
  act(() =>
    result.current.resumeTask("papers", {
      task_id: "kb_init_old",
      stage: "starting",
    }),
  );
  const oldStream = Stream.instances[0];
  const oldSocket = Socket.instances[0];
  act(() =>
    result.current.resumeTask("papers", {
      task_id: "kb_reindex_new",
      stage: "processing_documents",
      progress_percent: 20,
    }),
  );
  act(() => {
    oldStream.emit("progress", { progress_percent: 99 });
    oldStream.emit("complete", {});
    oldSocket.onmessage?.({
      data: JSON.stringify({ stage: "completed", task_id: "kb_init_old" }),
    });
  });
  expect(result.current.progressByKb.papers.progress_percent).toBe(20);
  expect(result.current.tasksByKb.papers.executing).toBe(true);
  expect(Stream.instances[1].close).not.toHaveBeenCalled();
  act(() =>
    Stream.instances[1].emit("process_log", { message: "New run is active" }),
  );
  expect(result.current.tasksByKb.papers.logs).toContain("New run is active");
});
