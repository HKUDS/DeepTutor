import { StrictMode, useCallback } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { useMasteryStudySession } from "@/hooks/useMasteryStudySession";
import { useMasteryOpening } from "@/hooks/useMasteryOpening";
import { isMasteryDraftSendReady } from "@/lib/mastery-study-route";
import { setPendingPrompt } from "@/lib/pending-prompt";
import { MASTERY_OPENING_SCOPE } from "@/lib/mastery-mode";
import { initI18n } from "@/i18n/init";

initI18n("en");
const mocks = vi.hoisted(() => ({
  topic: vi.fn(),
  sessions: vi.fn(),
  getSession: vi.fn(),
  replace: vi.fn(),
  requests: [] as Record<string, unknown>[],
  emit: undefined as undefined | ((event: Record<string, unknown>) => void),
}));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const router = { replace: mocks.replace };
vi.mock("@/lib/learning-api", () => ({
  fetchMasteryTopic: mocks.topic,
  fetchMasteryTopicSessions: mocks.sessions,
}));
vi.mock("@/lib/session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  getSession: mocks.getSession,
}));
vi.mock("@/hooks/useMasteryPathActivity", () => ({
  useMasteryPathActivity: () => ({ revision: 0 }),
}));
vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: class {
    connected = true;
    constructor(emit: typeof mocks.emit) {
      mocks.emit = emit;
    }
    connect() {}
    disconnect() {}
    setResumeState() {}
    send(message: Record<string, unknown>) {
      mocks.requests.push(message);
    }
    sendAwaitingAck(message: Record<string, unknown>) {
      mocks.requests.push(message);
      return Promise.resolve(true);
    }
  },
}));
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const topic = (pathId: string) => ({
  path_id: pathId,
  sources: [],
  map: { modules: [], counts: { mastered: 0, learning: 0, new: 0, total: 0 } },
});
function Harness({
  pathId,
  sessionId,
}: {
  pathId: string;
  sessionId?: string;
}) {
  const { state, sendMessage } = useChatStateAdapter();
  const session = useMasteryStudySession(pathId, sessionId, "", "outline");
  const submit = useCallback(
    (content: string) => {
      if (session.sessionLoading || session.sessionError || state.isStreaming)
        return false;
      sendMessage(content);
      return true;
    },
    [
      sendMessage,
      session.sessionLoading,
      session.sessionError,
      state.isStreaming,
    ],
  );
  useMasteryOpening({
    pathId,
    topicReady: Boolean(session.topic),
    hasMessages: state.messages.length > 0,
    sessionLoading: session.sessionLoading,
    sessionError: session.sessionError,
    sessionMode: session.sessionMode,
    isStreaming: state.isStreaming,
    submit,
  });
  return (
    <>
      <span data-testid="loading">{String(session.sessionLoading)}</span>
      <span data-testid="error">{session.sessionError}</span>
      <span data-testid="server-id">{state.sessionId ?? "none"}</span>
    </>
  );
}
const view = (pathId: string, sessionId?: string) => (
  <StrictMode>
    <ChatStateAdapterProvider>
      <Harness pathId={pathId} sessionId={sessionId} />
    </ChatStateAdapterProvider>
  </StrictMode>
);
const starts = () => mocks.requests.filter((r) => r.type === "start_turn");
beforeEach(() => {
  mocks.requests.length = 0;
  mocks.emit = undefined;
  mocks.topic.mockReset();
  mocks.sessions.mockReset();
  mocks.getSession.mockReset();
  mocks.replace.mockClear();
});

describe("mastery opening binding", () => {
  it("waits for an empty topic's draft and sends exactly once with its path", async () => {
    const pending = deferred<ReturnType<typeof topic>>();
    mocks.topic.mockReturnValue(pending.promise);
    setPendingPrompt("Design my outline", MASTERY_OPENING_SCOPE);
    render(view("topic_created"));
    expect(starts()).toHaveLength(0);
    expect(screen.getByTestId("loading")).toHaveTextContent("true");
    await act(async () => pending.resolve(topic("topic_created")));
    await waitFor(() => expect(starts()).toHaveLength(1));
    expect(starts()[0]).toMatchObject({
      workspace_mode: "mastery_path",
      mastery_path_id: "topic_created",
      mastery_session_mode: "outline",
      content: "Design my outline",
    });
    expect(screen.getByTestId("server-id")).toHaveTextContent("none");
    await act(async () =>
      mocks.emit?.({
        type: "session",
        metadata: { session_id: "unified_bound" },
      }),
    );
    await waitFor(() =>
      expect(mocks.replace).toHaveBeenCalledWith(
        "/mastery/topic_created/sessions/unified_bound",
        {
          scroll: false,
        },
      ),
    );
    expect(starts()).toHaveLength(1);
  });

  it("ignores a delayed topic after switching paths", async () => {
    const old = deferred<ReturnType<typeof topic>>();
    const next = deferred<ReturnType<typeof topic>>();
    mocks.topic.mockImplementation((id: string) =>
      id === "topic_old" ? old.promise : next.promise,
    );
    const rendered = render(view("topic_old"));
    rendered.rerender(view("topic_next"));
    await act(async () => old.resolve(topic("topic_old")));
    expect(starts()).toHaveLength(0);
    await act(async () => next.resolve(topic("topic_next")));
    await waitFor(() => expect(starts()).toHaveLength(1));
    expect(starts()[0]).toMatchObject({ mastery_path_id: "topic_next" });
  });

  it("does not send when existing-session membership fails", async () => {
    mocks.topic.mockResolvedValue(topic("topic_created"));
    mocks.sessions.mockResolvedValue([]);
    render(view("topic_created", "other_session"));
    await waitFor(() =>
      expect(screen.getByTestId("error").textContent).toContain(
        "different topic",
      ),
    );
    expect(starts()).toHaveLength(0);
  });

  it("blocks opening while an existing session loads and after failure", async () => {
    const pending = deferred<never>();
    mocks.topic.mockResolvedValue(topic("topic_created"));
    mocks.sessions.mockResolvedValue([{ session_id: "session_saved" }]);
    mocks.getSession.mockReturnValue(pending.promise);
    render(view("topic_created", "session_saved"));
    await waitFor(() => expect(mocks.getSession).toHaveBeenCalled());
    expect(starts()).toHaveLength(0);
    await act(async () => pending.reject(new Error("Session unavailable")));
    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent(
        "Session unavailable",
      ),
    );
    expect(starts()).toHaveLength(0);
  });

  it("preserves an existing session's stored study mode", async () => {
    mocks.topic.mockResolvedValue(topic("topic_created"));
    mocks.sessions.mockResolvedValue([{ session_id: "session_saved" }]);
    mocks.getSession.mockResolvedValue({
      session_id: "session_saved",
      messages: [],
      preferences: {
        workspace_mode: "mastery_path",
        mastery_path_id: "topic_created",
        mastery_session_mode: "study",
      },
    });
    render(view("topic_created", "session_saved"));
    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("server-id")).toHaveTextContent("session_saved");
    expect(starts()).toHaveLength(0);
  });

  it("discards an in-flight session snapshot after switching paths", async () => {
    const pending = deferred<Record<string, unknown>>();
    mocks.topic.mockImplementation((id: string) => Promise.resolve(topic(id)));
    mocks.sessions.mockResolvedValue([{ session_id: "session_old" }]);
    mocks.getSession.mockReturnValue(pending.promise);
    const rendered = render(view("topic_old", "session_old"));
    await waitFor(() => expect(mocks.getSession).toHaveBeenCalled());
    const signal = mocks.getSession.mock.calls[0][1] as AbortSignal;
    rendered.rerender(view("topic_next"));
    await waitFor(() => expect(starts()).toHaveLength(1));
    expect(signal.aborted).toBe(true);
    await act(async () =>
      pending.resolve({ session_id: "session_old", messages: [] }),
    );
    expect(screen.getByTestId("server-id")).toHaveTextContent("none");
    expect(starts()).toHaveLength(1);
  });

  it("ignores an old membership response after navigating to a new draft", async () => {
    const membership = deferred<unknown[]>();
    mocks.topic.mockImplementation((id: string) => Promise.resolve(topic(id)));
    mocks.sessions.mockReturnValue(membership.promise);
    const rendered = render(view("topic_old", "old_session"));
    await waitFor(() => expect(mocks.sessions).toHaveBeenCalled());
    rendered.rerender(view("topic_next"));
    await waitFor(() => expect(starts()).toHaveLength(1));
    await act(async () => membership.resolve([{ session_id: "old_session" }]));
    expect(starts()).toHaveLength(1);
    expect(screen.getByTestId("error")).toBeEmptyDOMElement();
  });
});

it("only admits the exact committed draft and configuration", () => {
  const ready = {
    binding: { routeKey: "topic:new", draftKey: "draft-new" },
    routeKey: "topic:new",
    sessionKey: "draft-new",
    workspaceMode: "mastery_path",
    masteryPathId: "topic",
    pathId: "topic",
    masterySessionMode: "outline",
    requestedMode: "outline",
  };
  expect(isMasteryDraftSendReady(ready)).toBe(true);
  for (const override of [
    { binding: null },
    { sessionKey: "old-session" },
    { sessionKey: "draft-old" },
    { routeKey: "other:new" },
    { workspaceMode: "chat" },
    { masteryPathId: "other" },
    { masterySessionMode: "study" },
  ])
    expect(isMasteryDraftSendReady({ ...ready, ...override })).toBe(false);
});
