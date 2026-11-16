import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useMcpServers } from "@/hooks/useMcpServers";
import { SPACE_MCP_SURFACE } from "@/components/mcp/surface";

const fixture = vi.hoisted(() => ({ load: vi.fn(), authorize: vi.fn(), t: (key: string) => key }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: fixture.t }) }));
vi.mock("@/components/mcp/surface", async (original) => ({
  ...await original<object>(), loadMcpSurface: fixture.load,
}));
vi.mock("@/lib/mcp-api", async (original) => ({
  ...await original<object>(), authorizeSpaceMcpServer: fixture.authorize,
}));
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it("refreshes pending consent until connected and cancels polling on unmount", async () => {
  vi.useFakeTimers();
  vi.spyOn(window, "open").mockReturnValue(null);
  const state = (authorized: boolean) => ({
    servers: { notes: { enabled: true, auth: "oauth" } },
    status: [{ name: "notes", status: authorized ? "connected" : "needs_auth" }],
    user: { oauth: { notes: { authorized } } },
  });
  fixture.load.mockResolvedValue(state(false));
  fixture.authorize.mockResolvedValue("https://example.test/consent");
  const hook = renderHook(() => useMcpServers(SPACE_MCP_SURFACE));
  await act(async () => {});
  expect(hook.result.current.statusByName.get("notes")?.status).toBe("needs_auth");
  await act(async () => { await hook.result.current.authorize("notes"); });
  await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
  expect(fixture.load).toHaveBeenCalledTimes(2);
  fixture.load.mockResolvedValue(state(true));
  await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
  expect(hook.result.current.statusByName.get("notes")?.status).toBe("connected");
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(fixture.load).toHaveBeenCalledTimes(3);
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  expect(fixture.load).toHaveBeenCalledTimes(4);
  hook.unmount();
  await vi.advanceTimersByTimeAsync(3000);
  window.dispatchEvent(new Event("focus"));
  expect(fixture.load).toHaveBeenCalledTimes(4);
});
