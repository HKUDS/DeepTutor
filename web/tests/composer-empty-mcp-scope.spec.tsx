import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useComposerResources } from "@/hooks/useComposerResources";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch: api.fetch, apiUrl: (url: string) => url }));

function workspace(mcp: string[] | null): ChatWorkspaceRegistration {
  return {
    workspace_id: "workspace-a", kind: "workspace", follows_root: true,
    display_name: "Workspace A", path: "/workspace-a", archived: false,
    created_at: "2026-10-05T00:00:00Z", status: "ready", error: "",
    resources: { skills: null, mcp, knowledge_bases: null },
  };
}

function catalog() {
  api.fetch.mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
    skills: [{ id: "skill-a", name: "Skill A" }],
    mcp: [{ id: "server-a", name: "Server A" }, { id: "server-b", name: "Server B" }],
    knowledge_bases: [],
  }))));
}

describe("composer MCP workspace selection", () => {
  it.each([
    [null, ["server-a", "server-b"]],
    [["server-a"], ["server-a"]],
    [[], []],
  ] as const)("respects configured MCP selection %j", async (mcp, expected) => {
    catalog();
    const { result } = renderHook(() => useComposerResources("workspace-a", [workspace(mcp ? [...mcp] : null)]));
    await waitFor(() => expect(result.current.skills).toHaveLength(1));
    expect(result.current.mcp.map(option => option.id)).toEqual(expected);
  });

  it("refreshes when an inherited selection becomes explicitly empty", async () => {
    catalog();
    const { result, rerender } = renderHook(({ mcp }: { mcp: string[] | null }) =>
      useComposerResources("workspace-a", [workspace(mcp)]),
    { initialProps: { mcp: null } as { mcp: string[] | null } });
    await waitFor(() => expect(result.current.mcp).toHaveLength(2));
    rerender({ mcp: [] });
    await waitFor(() => expect(result.current.mcp).toHaveLength(0));
  });
});
