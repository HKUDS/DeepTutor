import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useSetupSync } from "@/hooks/useSetupSync";
import type { StreamEvent } from "@/features/chat/model/protocol";

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch: api.fetch, apiUrl: (url: string) => url }));

function messages(id = "call-1") {
  return [{ events: [{ type: "tool_result", source: "setup", stage: "loop",
    content: "", session_id: "session-1", turn_id: "turn-1", seq: 1, timestamp: 0,
    metadata: { tool_call_id: id, tool_metadata: { setup_applied: { key: "interface.language" } } },
  } as StreamEvent] }];
}

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>(done => { resolve = done; });
  return { promise, resolve };
}

async function finish(resolve: (response: Response) => void, language: string) {
  await act(async () => {
    resolve(new Response(JSON.stringify({ language, response_language: language })));
  });
}

describe("setup preference synchronization during a streamed turn", () => {
  it("honors the setting through strict-mode effect replay", async () => {
    localStorage.clear();
    const pending = deferredResponse();
    api.fetch.mockReset().mockReturnValue(pending.promise);
    renderHook(() => useSetupSync(messages()), { reactStrictMode: true });
    await finish(pending.resolve, "zh");
    expect(localStorage.getItem("deeptutor-language")).toBe("zh");
    expect(api.fetch).toHaveBeenCalledTimes(1);
  });

  it("applies the response after an ordinary message update", async () => {
    localStorage.clear();
    const pending = deferredResponse();
    api.fetch.mockReset().mockReturnValue(pending.promise);
    const { rerender } = renderHook(({ items }) => useSetupSync(items), {
      initialProps: { items: messages() },
    });
    rerender({ items: messages() });
    await finish(pending.resolve, "zh");
    expect(localStorage.getItem("deeptutor-language")).toBe("zh");
    expect(api.fetch).toHaveBeenCalledTimes(1);
    rerender({ items: messages() });
    expect(api.fetch).toHaveBeenCalledTimes(1);
  });

  it("does not apply a response after unmount", async () => {
    localStorage.clear();
    const pending = deferredResponse();
    api.fetch.mockReset().mockReturnValue(pending.promise);
    const { unmount } = renderHook(() => useSetupSync(messages()));
    unmount();
    await finish(pending.resolve, "zh");
    expect(localStorage.getItem("deeptutor-language")).toBeNull();
  });

  it("keeps the newest applied setting when responses arrive out of order", async () => {
    localStorage.clear();
    const first = deferredResponse();
    const second = deferredResponse();
    api.fetch.mockReset().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { rerender } = renderHook(({ items }) => useSetupSync(items), {
      initialProps: { items: messages() },
    });
    rerender({ items: messages("call-2") });
    await finish(second.resolve, "zh");
    await finish(first.resolve, "en");
    expect(localStorage.getItem("deeptutor-language")).toBe("zh");
  });
});
