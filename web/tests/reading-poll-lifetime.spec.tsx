import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { useReadingWorkspace } from "@/components/reading/workspace/useReadingWorkspace";
import { apiFetch } from "@/lib/api";

const stable = vi.hoisted(() => ({
  t: (key: string) => key,
  noop: () => undefined,
  state: { sessionId: null },
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: stable.t }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: stable.noop }) }));
vi.mock("@/context/ReadingContext", () => ({
  useReading: () => ({ material: null, annotations: [], openMaterial: stable.noop, closeMaterial: stable.noop, reportViewport: stable.noop }),
}));
vi.mock("@/features/chat/ChatStateAdapter", () => ({
  useChatStateAdapter: () => ({ state: stable.state, configureSession: stable.noop, loadSession: stable.noop, newSession: stable.noop }),
}));
vi.mock("@/lib/api", () => ({ apiUrl: (url: string) => url, apiFetch: vi.fn() }));

afterEach(() => vi.useRealTimers());

function workspaceResponse(status: string) {
  return new Response(JSON.stringify({ workspace: {
    workspace_id: "collection", title: "Collection", description: "", active_material_id: "material", created_at: 1, updated_at: 1,
    tabs: [{ material: { material_id: "material", status }, tab_order: 0, pinned: false, opened: false, added_at: 1 }],
  }, sessions: [] }), { headers: { "Content-Type": "application/json" } });
}

async function startPoll() {
  vi.useFakeTimers();
  let complete!: (response: Response) => void;
  let reads = 0;
  vi.mocked(apiFetch).mockImplementation(async (url) => {
    if (String(url).endsWith("/sessions")) return new Response('{"sessions":[]}');
    reads += 1;
    if (reads === 2) return new Promise((resolve) => { complete = resolve; });
    return workspaceResponse("queued");
  });
  const hook = renderHook(() => useReadingWorkspace("collection", null));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(reads).toBe(2);
  return { hook, complete, reads: () => reads };
}

it("does not restart polling when an in-flight response arrives after unmount", async () => {
  const probe = await startPoll();
  probe.hook.unmount();
  await act(async () => { probe.complete(workspaceResponse("queued")); await vi.advanceTimersByTimeAsync(10_000); });
  expect(probe.reads()).toBe(2);
});

it("stops polling when the current response settles all materials", async () => {
  const probe = await startPoll();
  await act(async () => { probe.complete(workspaceResponse("failed")); await vi.advanceTimersByTimeAsync(0); });
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  expect(probe.reads()).toBe(2);
});

it("retains the retry loop and reports a failed polling request", async () => {
  const probe = await startPoll();
  await act(async () => {
    probe.complete(new Response('{"detail":"Temporarily unavailable"}', { status: 503 }));
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(probe.hook.result.current.notice).toBe("Temporarily unavailable");
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(probe.reads()).toBe(3);
});
