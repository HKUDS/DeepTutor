import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NoteSummary } from "@/lib/notes-api";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";

const state = vi.hoisted(() => ({
  scope: "",
  workspaceRows: [] as unknown[],
  notes: [] as unknown[],
}));

vi.mock("@/lib/workspace-scope", () => ({
  activeWorkspaceId: () => state.scope,
}));
vi.mock("@/lib/session-events", () => ({
  subscribeSessionChanges: () => () => {},
}));
vi.mock("@/lib/workspaces-api", () => ({
  listWorkspaces: async () => state.workspaceRows,
}));
vi.mock("@/lib/api", () => ({
  apiFetch: async () =>
    ({ ok: true, status: 200, json: async () => ({ documents: state.notes }) }) as Response,
  apiUrl: (path: string) => path,
}));

const wsRow = {
  workspace_id: "w1",
  kind: "workspace",
  display_name: "Probability",
  path: "",
  follows_root: false,
  archived: false,
} as ChatWorkspaceRegistration;

beforeEach(() => {
  state.scope = "";
  state.workspaceRows = [];
  state.notes = [];
});

describe("route-rebuild caches", () => {
  it("keeps the sidebar snapshot for the next mount and applies list edits", async () => {
    const cache = await import("@/components/sidebar/sidebar-session-cache");
    const first = { session_id: "s1" } as never;
    const second = { session_id: "s2" } as never;

    expect(cache.readSidebarSessionCache("w1")).toBeNull();
    cache.writeSidebarSessionCache("w1", {
      sessions: [first],
      masteryTopics: [],
      readingCollections: [],
    });
    expect(cache.readSidebarSessionCache("w1")?.sessions).toEqual([first]);

    cache.updateCachedSessions("w1", (prev) => [...prev, second]);
    expect(cache.readSidebarSessionCache("w1")?.sessions).toEqual([first, second]);

    // Renaming or deleting from a surface whose workspace never cached must not
    // fabricate an entry.
    cache.updateCachedSessions("unknown", () => []);
    expect(cache.readSidebarSessionCache("unknown")).toBeNull();
  });

  it("restores workspaces on remount before any fetch lands", async () => {
    state.workspaceRows = [wsRow, { ...wsRow, workspace_id: "sys", kind: "system" }];
    const { useChatWorkspaces } = await import("@/hooks/useChatWorkspaces");

    const first = renderHook(() => useChatWorkspaces());
    expect(first.result.current.loaded).toBe(false);
    await waitFor(() => expect(first.result.current.loaded).toBe(true));
    expect(first.result.current.workspaces).toEqual([wsRow]);
    first.unmount();

    // The second mount (another route group's sidebar) must not start empty.
    const second = renderHook(() => useChatWorkspaces());
    expect(second.result.current.loaded).toBe(true);
    expect(second.result.current.workspaces).toEqual([wsRow]);
    await act(async () => {});
  });

  it("caches note lists per workspace so a revisit paints instantly", async () => {
    state.scope = "w1";
    state.notes = [{ id: "n1", title: "Lecture" }];
    const notesApi = await import("@/lib/notes-api");

    expect(notesApi.peekCachedNotes()).toBeNull();
    await notesApi.listNotes();
    expect(notesApi.peekCachedNotes()).toEqual(state.notes);

    // Another workspace must never see the first one's pages.
    state.scope = "w2";
    expect(notesApi.peekCachedNotes()).toBeNull();
  });
});
