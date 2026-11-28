import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import { ChatStateAdapterProvider, useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import type { SessionDetail, SessionSummary } from "@/lib/session-api";
import { notifySessionsChanged } from "@/lib/session-events";
import { registerWorkspaceNavigator } from "@/lib/workspace-scope";

const fixture = vi.hoisted(() => ({
  push: vi.fn(),
  getSession: vi.fn(),
  deleteSession: vi.fn(),
  updateSessionOrganization: vi.fn(),
  session: {} as SessionSummary,
  visible: true,
  running: new Set<string>(),
  clients: [] as Array<{
    emit: (event: Record<string, unknown>) => void;
    send: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
    cancelCurrentTurn: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: fixture.push }) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/lib/session-api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/session-api")>(),
  listAllSessions: async () => fixture.visible ? [fixture.session] : [],
  getSession: fixture.getSession,
  deleteSession: fixture.deleteSession,
  updateSessionOrganization: fixture.updateSessionOrganization,
}));
vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: class {
    connected = true;
    send = vi.fn();
    disconnect = vi.fn();
    cancelCurrentTurn = vi.fn(async () => true);
    constructor(public emit: (event: Record<string, unknown>) => void) {
      fixture.clients.push(this);
    }
    connect() {}
    setResumeState() {}
  },
}));
vi.mock("@/lib/learning-api", () => ({ fetchMasteryTopicIndex: async () => [] }));
vi.mock("@/lib/reading-workspace-api", () => ({ fetchReadingCollectionIndex: async () => [] }));
vi.mock("@/features/ui-layout/slots", async () => {
  const { default: OrganizedSessionList } = await import("@/components/sessions/OrganizedSessionList");
  return {
    LayoutSidebarShell: (props: import("@/features/ui-layout/types").SidebarShellProps) => (
      <OrganizedSessionList
        sessions={props.sessions ?? []}
        activeSessionId={props.activeSessionId ?? null}
        workspaces={[{
          workspace_id: "other", display_name: "Other workspace", kind: "workspace",
          follows_root: false, path: "/other", archived: false,
          created_at: "2026-01-01", status: "ready", error: "",
        }]}
        onSelect={props.onSelectSession!}
        onRename={props.onRenameSession!}
        onDelete={props.onDeleteSession!}
        onOrganize={props.onOrganizeSession!}
      />
    ),
  };
});

let runtime: ReturnType<typeof useChatStateAdapter>;
function RuntimeProbe() {
  const chat = useChatStateAdapter();
  useLayoutEffect(() => { runtime = chat; });
  return <output data-testid="transcript">{chat.state.messages.map(message => message.content).join("|")}</output>;
}

function detail(id: string): SessionDetail {
  const running = fixture.running.has(id);
  return {
    ...fixture.session,
    id, session_id: id,
    updated_at: Date.now() / 1000,
    status: running ? "running" : "completed",
    active_turns: running ? [{
      id: `turn-${id}`, turn_id: `turn-${id}`, session_id: id,
      capability: "chat", status: "running", error: "",
      created_at: Date.now() / 1000, updated_at: Date.now() / 1000, last_seq: 0,
    }] : [],
    messages: [{
      id: 1, session_id: id, role: "user", content: `Transcript of ${id}`,
      created_at: 1, events: [], attachments: [], metadata: {}, parent_message_id: null,
    }],
  };
}

let unregister: () => void;
beforeEach(() => {
  fixture.visible = true;
  fixture.running.clear();
  fixture.clients = [];
  fixture.session = {
    id: "session-1", session_id: "session-1", title: "Previously opened chat",
    created_at: 1, updated_at: 1, message_count: 1, last_message: "Hello",
    content_workspace_id: "", preferences: {},
  };
  fixture.getSession.mockReset().mockImplementation(async (id: string) => {
    if (id === "session-1" && !fixture.visible) throw new Error("Session not found in this workspace");
    return detail(id);
  });
  fixture.deleteSession.mockReset().mockImplementation(async () => {
    fixture.visible = false;
    notifySessionsChanged();
  });
  fixture.updateSessionOrganization.mockReset().mockImplementation(async (_id, patch) => {
    fixture.visible = !patch.workspace_id;
    notifySessionsChanged();
    return { ...detail("session-1"), preferences: { ...fixture.session.preferences, ...patch } };
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  window.history.replaceState(null, "", "/chat/session-1?dt_workspace=");
  unregister = registerWorkspaceNavigator(fixture.push);
});
afterEach(() => unregister());

async function mountSidebar(selected = "session-1") {
  render(<ChatStateAdapterProvider><WorkspaceSidebar /><RuntimeProbe /></ChatStateAdapterProvider>);
  await screen.findByText("Previously opened chat");
  await act(async () => { await runtime.loadSession(selected); });
}

async function startMutation(operation: "delete" | "move", destination = "Other workspace") {
  fireEvent.click(await screen.findByRole("button", { name: "Conversation actions" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("menuitem", { name: operation === "delete" ? "Delete chat" : destination }));
  });
}

async function mutateSession(operation: "delete" | "move") {
  await startMutation(operation);
  await waitFor(() => expect(screen.queryByText("Previously opened chat")).not.toBeInTheDocument());
}

function delayMutation(operation: "delete" | "move") {
  let finish!: () => void;
  const pending = new Promise<void>(resolve => { finish = resolve; });
  const mock = operation === "delete" ? fixture.deleteSession : fixture.updateSessionOrganization;
  const perform = mock.getMockImplementation()!;
  mock.mockImplementationOnce(async (...args: unknown[]) => { await pending; return perform(...args); });
  return finish;
}

for (const operation of ["delete", "move"] as const) {
  describe(operation, () => {
    it.each(["/space", "/space/chat-history", "/personalization", "/agents"])(
      "stays on %s and evicts the previously selected session",
      async (pathname) => {
        await mountSidebar();
        window.history.replaceState(null, "", `${pathname}?dt_workspace=`);
        await mutateSession(operation);
        expect(fixture.push).not.toHaveBeenCalled();
        expect(window.location.pathname).toBe(pathname);
        expect(runtime.selectedSessionId).toBeNull();
        let cached = true;
        await act(async () => { cached = runtime.showCachedSession("session-1"); });
        expect(cached).toBe(false);
        expect(screen.getByTestId("transcript")).not.toHaveTextContent("Transcript of session-1");
      },
    );

    it.each([
      { path: "/chat/session-1", preferences: {}, afterDelete: "/chat", afterMove: "/chat/session-1" },
      {
        path: "/learning/reading/collection-1/sessions/session-1",
        preferences: { workspace_mode: "immersive_reading", reading_workspace_id: "collection-1" },
        afterDelete: "/learning/reading/collection-1", afterMove: "/learning/reading/collection-1/sessions/session-1",
      },
      {
        path: "/learning/mastery/topic-1/sessions/session-1",
        preferences: { workspace_mode: "mastery_path", mastery_path_id: "topic-1" },
        afterDelete: "/chat", afterMove: "/learning/mastery/topic-1/sessions/session-1",
      },
      {
        path: "/learning/watching/session-1", preferences: { workspace_mode: "immersive_watching" },
        afterDelete: "/chat", afterMove: "/learning/watching/session-1",
      },
      {
        path: "/chat/session-1", preferences: { workspace_mode: "mastery_path", mastery_path_id: "topic-1" },
        afterDelete: "/chat", afterMove: "/learning/mastery/topic-1/sessions/session-1",
      },
      {
        path: "/chat/session-1", preferences: { workspace_mode: "immersive_reading", reading_workspace_id: "collection-1" },
        afterDelete: "/learning/reading/collection-1", afterMove: "/learning/reading/collection-1/sessions/session-1",
      },
    ] as const)("navigates from the displayed session at $path with $preferences", async ({ path, preferences, afterDelete, afterMove }) => {
      fixture.session.preferences = preferences;
      window.history.replaceState(null, "", `${path}?dt_workspace=`);
      await mountSidebar();
      await mutateSession(operation);
      expect(fixture.push).toHaveBeenCalledExactlyOnceWith(
        operation === "delete" ? `${afterDelete}?dt_workspace=` : `${afterMove}?dt_workspace=other`,
      );
    });

    it.each([
      "/chat/session-1?workspace=",
      "/chat/%73ession-1?dt_workspace=&tab=messages",
      "/chat/session-1",
    ])("recognizes the equivalent session URL %s", async url => {
      await mountSidebar();
      window.history.replaceState(null, "", url);
      await mutateSession(operation);
      expect(fixture.push).toHaveBeenCalledExactlyOnceWith(
        operation === "delete" ? "/chat?dt_workspace=" : "/chat/session-1?dt_workspace=other",
      );
    });

    it.each([
      { path: "/chat/session-1?dt_workspace=elsewhere", preferences: {} },
      { path: "/learning/books/book-1/pages/page-1?chat=another&dt_workspace=", preferences: { book_id: "book-1", book_page_id: "page-1" } },
      { path: "/space?chat=session-1&dt_workspace=", preferences: {} },
    ])("does not navigate from a different conversation or store: $path", async ({ path, preferences }) => {
      fixture.session.preferences = preferences;
      await mountSidebar();
      window.history.replaceState(null, "", path);
      await mutateSession(operation);
      expect(fixture.push).not.toHaveBeenCalled();
    });

    it("does not pull the user back after leaving during the request", async () => {
      const finish = delayMutation(operation);
      await mountSidebar();
      await startMutation(operation);
      window.history.replaceState(null, "", "/space?dt_workspace=");
      await act(async () => finish());
      expect(fixture.push).not.toHaveBeenCalled();
      expect(runtime.selectedSessionId).toBeNull();
    });

    it("preserves B's selected state, transcript and running turn when A's request finishes", async () => {
      const finish = delayMutation(operation);
      await mountSidebar();
      await startMutation(operation);
      fixture.running.add("session-2");
      window.history.replaceState(null, "", "/chat/session-2?dt_workspace=");
      await act(async () => { await runtime.loadSession("session-2"); });
      const runnerB = fixture.clients[0];
      expect(runtime.state.isStreaming).toBe(true);
      await act(async () => finish());
      expect(runtime.selectedSessionId).toBe("session-2");
      expect(screen.getByTestId("transcript")).toHaveTextContent("Transcript of session-2");
      expect(runtime.state.isStreaming).toBe(true);
      expect(runnerB.cancelCurrentTurn).not.toHaveBeenCalled();
      expect(runnerB.disconnect).not.toHaveBeenCalled();
      expect(fixture.push).not.toHaveBeenCalled();
    });

    it("navigates if A becomes the displayed session while its request is pending", async () => {
      const finish = delayMutation(operation);
      window.history.replaceState(null, "", "/chat/session-2?dt_workspace=");
      await mountSidebar("session-2");
      await startMutation(operation);
      window.history.replaceState(null, "", "/chat/session-1?dt_workspace=");
      await act(async () => { await runtime.loadSession("session-1"); });
      await act(async () => finish());
      expect(fixture.push).toHaveBeenCalledExactlyOnceWith(
        operation === "delete" ? "/chat?dt_workspace=" : "/chat/session-1?dt_workspace=other",
      );
    });

    it("cannot reopen the old cached transcript after returning from Resources", async () => {
      await mountSidebar();
      window.history.replaceState(null, "", "/space?dt_workspace=");
      await mutateSession(operation);
      window.history.replaceState(null, "", "/chat/session-1?dt_workspace=");
      let cached = true;
      await act(async () => {
        cached = runtime.showCachedSession("session-1");
        await expect(runtime.loadSession("session-1", { revalidate: cached })).rejects.toThrow("Session not found");
      });
      expect(cached).toBe(false);
      expect(screen.getByTestId("transcript")).not.toHaveTextContent("Transcript of session-1");
    });

    it("discards a load response that predates the successful mutation", async () => {
      await mountSidebar();
      const stale = detail("session-1");
      let finishLoad!: (value: SessionDetail) => void;
      fixture.getSession.mockReturnValueOnce(new Promise<SessionDetail>(resolve => { finishLoad = resolve; }));
      let loading!: ReturnType<typeof runtime.loadSession>;
      await act(async () => { loading = runtime.loadSession("session-1"); });
      window.history.replaceState(null, "", "/space?dt_workspace=");
      await mutateSession(operation);
      await act(async () => { finishLoad(stale); await loading; });
      let cached = true;
      await act(async () => { cached = runtime.showCachedSession("session-1"); });
      expect(cached).toBe(false);
      expect(runtime.selectedSessionId).toBeNull();
    });
  });
}

it("disconnects only the deleted session and ignores its late transport events", async () => {
  fixture.running.add("session-1");
  await mountSidebar();
  const runnerA = fixture.clients[0];
  await mutateSession("delete");
  expect(runnerA.disconnect).toHaveBeenCalledOnce();
  expect(runnerA.cancelCurrentTurn).not.toHaveBeenCalled();
  await act(async () => runnerA.emit({ type: "session", session_id: "session-1", turn_id: "turn-session-1" }));
  expect(runtime.selectedSessionId).toBeNull();
});

it("keeps post-DONE title updates from a normally completed runner", async () => {
  fixture.running.add("session-1");
  await mountSidebar();
  const runner = fixture.clients[0];
  vi.useFakeTimers();
  try {
    await act(async () => runner.emit({
      type: "done", session_id: "session-1", turn_id: "turn-session-1",
      metadata: { status: "completed", user_message_id: 1, assistant_message_id: 2 },
    }));
    await act(async () => runner.emit({ type: "session_meta", metadata: { title: "Generated title" } }));
    expect(runtime.state.sessionTitle).toBe("Generated title");
  } finally {
    vi.clearAllTimers();
    vi.useRealTimers();
  }
});

it("keeps a conversation in memory when its workspace did not change", async () => {
  await mountSidebar();
  window.history.replaceState(null, "", "/space?dt_workspace=");
  await startMutation("move", "General workspace");
  expect(runtime.selectedSessionId).toBe("session-1");
  expect(screen.getByTestId("transcript")).toHaveTextContent("Transcript of session-1");
  expect(fixture.push).not.toHaveBeenCalled();
});
