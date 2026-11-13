import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useReadingWorkspace } from "@/components/reading/workspace/useReadingWorkspace";

const mocks = vi.hoisted(() => ({
  state: { sessionId: "chat-old" as string | null },
  newSession: vi.fn(), loadSession: vi.fn().mockResolvedValue(undefined),
  configureSession: vi.fn(), getWorkspace: vi.fn(),
  reading: { material: null, annotations: [], openMaterial: vi.fn(), closeMaterial: vi.fn(), reportViewport: vi.fn() },
  router: { push: vi.fn() }, t: (key: string) => key,
}));
vi.mock("next/navigation", () => ({useRouter: () => mocks.router}));
vi.mock("react-i18next", () => ({useTranslation: () => ({t: mocks.t})}));
vi.mock("@/context/ReadingContext", () => ({useReading: () => mocks.reading}));
vi.mock("@/features/chat/ChatStateAdapter", () => ({useChatStateAdapter: () => mocks}));
vi.mock("@/lib/reading-turn-state", () => ({setReadingWorkspace: vi.fn()}));
vi.mock("@/lib/reading-workspace-api", async (original) => ({
  ...await original<typeof import("@/lib/reading-workspace-api")>(),
  getReadingWorkspace: mocks.getWorkspace,
  listReadingConversations: vi.fn().mockResolvedValue([]),
}));
const workspace = {workspace_id: "collection", title: "Book", active_material_id: null, tabs: []};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.state.sessionId = "chat-old";
  window.history.replaceState(null, "", "/learning/reading/collection");
});
it("does not adopt an inherited chat before or after asynchronous collection hydration", async () => {
  let resolve!: (value: unknown) => void;
  mocks.getWorkspace.mockReturnValue(new Promise(r => {resolve = r;}));
  const {rerender} = renderHook(() => useReadingWorkspace("collection", null));
  expect(window.location.pathname).toBe("/learning/reading/collection");
  expect(mocks.newSession).not.toHaveBeenCalled();
  await act(async () => {resolve({workspace});});
  await waitFor(() => expect(mocks.newSession).toHaveBeenCalledTimes(1));
  // The shared adapter can still expose the old id until its update renders.
  rerender();
  expect(window.location.pathname).toBe("/learning/reading/collection");
  mocks.state.sessionId = null;
  rerender();
  mocks.state.sessionId = "reading-new";
  rerender();
  expect(window.location.pathname).toBe("/learning/reading/collection/sessions/reading-new");
  expect(mocks.loadSession).not.toHaveBeenCalled();
});
it("loads an explicitly linked reading session instead of starting a draft", async () => {
  mocks.getWorkspace.mockResolvedValue({workspace});
  renderHook(() => useReadingWorkspace("collection", "reading-existing"));
  await waitFor(() => expect(mocks.loadSession).toHaveBeenCalledWith("reading-existing"));
  expect(mocks.newSession).not.toHaveBeenCalled();
  expect(mocks.configureSession).toHaveBeenCalledWith(expect.anything(), "reading-existing");
});
