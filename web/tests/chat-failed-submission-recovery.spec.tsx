import { act, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode, useEffect, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { initI18n } from "@/i18n/init";
import {
  resetReadingTurnState, setReadingMaterial, setReadingViewport,
  setReadingWorkspace,
} from "@/lib/reading-turn-state";
import {
  resetWatchingTurnState, setWatchingMaterial, setWatchingViewport,
} from "@/lib/watching-turn-state";
import {
  clearFailedSubmission,
  moveFailedSubmissions,
  readFailedSubmission,
  readFailedSubmissions,
  storeFailedSubmission,
} from "@/lib/failed-submissions";

initI18n("en");

const fixture = vi.hoisted(() => ({
  connected: false,
  sent: [] as Array<Record<string, unknown>>,
  emit: undefined as undefined | ((event: Record<string, unknown>) => void),
  close: undefined as undefined | (() => void),
  session: undefined as undefined | Record<string, unknown>,
}));

vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: class {
    constructor(
      emit: (event: Record<string, unknown>) => void,
      close: () => void,
    ) {
      fixture.emit = emit;
      fixture.close = close;
    }
    get connected() {
      return fixture.connected;
    }
    connect() {}
    disconnect() {}
    send(message: Record<string, unknown>) {
      fixture.sent.push(message);
    }
    sendAwaitingAck(message: Record<string, unknown>) {
      fixture.sent.push(message);
      return Promise.resolve(true);
    }
    setResumeState() {}
  },
}));

vi.mock("@/lib/session-api", () => ({
  getSession: async (sessionId: string) => {
    if (!fixture.session) throw new Error("no fixture session configured");
    return {
      ...JSON.parse(JSON.stringify(fixture.session)),
      session_id: sessionId,
      id: sessionId,
    };
  },
  getMessageTrace: async () => ({
    session_id: "",
    message_id: 0,
    events: [],
    total: 0,
  }),
  deleteMessage: async () => ({}),
  updateBranchSelection: async () => ({}),
  updateSessionTitle: async () => fixture.session ?? {},
  updateSessionReplyLanguage: async () => fixture.session ?? {},
}));

/** A server transcript: one completed user/assistant exchange. */
function completedServerSession() {
  return {
    id: "s1",
    session_id: "s1",
    title: "Chat",
    created_at: 1,
    updated_at: Date.now() / 1000,
    status: "completed",
    messages: [
      {
        id: 1,
        session_id: "s1",
        role: "user",
        content: "hi",
        events: [],
        attachments: [],
        created_at: 1,
        parent_message_id: null,
      },
      {
        id: 2,
        session_id: "s1",
        role: "assistant",
        content: "hello",
        events: [],
        attachments: [],
        created_at: 2,
        parent_message_id: 1,
      },
    ],
    preferences: {},
  };
}

function seedUnsentSubmission(content = "Hello offline") {
  return storeFailedSubmission("s1", {
    content,
    capability: "chat",
    requestSnapshot: {
      content,
      capability: "chat",
      enabledTools: [],
      knowledgeBases: [],
      language: "en",
    },
  });
}

function Harness() {
  const { state, sendMessage, resendLastMessage, loadSession, cancelStreamingTurn,
    configureSession, setPersonaSelection, setLLMSelection,
    setReplyLanguageOverride } =
    useChatStateAdapter();
  return (
    <>
      <button onClick={() => void loadSession("s1")}>Load</button>
      <button onClick={() => void loadSession("new-session")}>Load new</button>
      <button onClick={() => sendMessage("Hello offline")}>Send</button>
      <button onClick={() => sendMessage("Second offline")}>Send another</button>
      <button onClick={() => void resendLastMessage()}>Resend</button>
      <button onClick={cancelStreamingTurn}>Stop</button>
      <button onClick={() => {
        configureSession({
          capability: "deep_research", workspaceMode: "immersive_reading",
          workspaceId: "other-workspace", courseId: "other-course",
          masteryPathId: "other-path", masterySessionMode: "study",
        });
        setPersonaSelection("other-persona");
        setLLMSelection({ model_id: "other-model", profile_id: "other-profile" });
        void setReplyLanguageOverride("zh");
      }}>Change live settings</button>
      <button onClick={() => {
        configureSession({ workspaceMode: "immersive_reading", workspaceId: "ws-reading" });
        setReadingWorkspace("ws-reading");
        setReadingMaterial("deadbeef", 2);
        setReadingViewport({ locator: 7, selection: "old passage", timeSeconds: 12 });
      }}>Prepare reading</button>
      <button onClick={() => {
        configureSession({ capability: "immersive_watching", workspaceMode: "immersive_watching" });
        setWatchingMaterial("video-a");
        setWatchingViewport(42);
      }}>Prepare watching</button>
      <div data-testid="submissionFailed">
        {String(state.submissionFailed)}
      </div>
      <div data-testid="lastTurnFailed">{String(state.lastTurnFailed)}</div>
      <div data-testid="capability">{state.activeCapability}</div>
      <div data-testid="submissionNeedsReview">{String(state.submissionNeedsReview)}</div>
      <div data-testid="submissionNotSaved">{String(state.submissionNotSaved)}</div>
      <div data-testid="messages">
        {JSON.stringify(
          state.messages.map((message) => ({
            role: message.role,
            content: message.content,
            failed: message.failedSubmission === true,
          })),
        )}
      </div>
      <div data-testid="stored">
        {JSON.stringify(readFailedSubmissions("s1"))}
      </div>
    </>
  );
}

function BootstrapDraft() {
  const { newSession } = useChatStateAdapter();
  useEffect(() => {
    newSession({ capability: "deep_research" });
  }, [newSession]);
  return null;
}

function PersistentProviderRoutes() {
  const [onChat, setOnChat] = useState(true);
  return (
    <ChatStateAdapterProvider>
      <button onClick={() => setOnChat((value) => !value)}>Toggle chat route</button>
      {onChat ? <BootstrapDraft /> : null}
      <Harness />
    </ChatStateAdapterProvider>
  );
}

function readMessages() {
  return JSON.parse(
    screen.getByTestId("messages").textContent ?? "[]",
  ) as Array<{ role: string; content: string; failed: boolean }>;
}

function readStoredKeys() {
  return readFailedSubmissions("s1").length ? ["s1"] : [];
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  resetReadingTurnState();
  resetWatchingTurnState();
  fixture.connected = false;
  fixture.sent = [];
  fixture.emit = undefined;
  fixture.close = undefined;
});

afterEach(() => vi.restoreAllMocks());

it("marks a submission the server never received as unsent, not a failed reply", async () => {
  vi.useFakeTimers();
  try {
    fixture.session = completedServerSession();
    render(
      <ChatStateAdapterProvider>
        <Harness />
      </ChatStateAdapterProvider>,
    );
    await act(async () => {
      fireEvent.click(screen.getByText("Load"));
    });
    // Submit while the transport cannot connect. The retry schedule gives
    // up after ~2s of failed connection attempts.
    fireEvent.click(screen.getByText("Send"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_400);
    });
    // The optimistic user row is flagged unsent and NO assistant row was
    // left behind to masquerade as an errored reply.
    expect(readMessages()).toEqual([
      { role: "user", content: "hi", failed: false },
      { role: "assistant", content: "hello", failed: false },
      { role: "user", content: "Hello offline", failed: true },
    ]);
    expect(screen.getByTestId("submissionFailed").textContent).toBe("true");
    expect(screen.getByTestId("lastTurnFailed").textContent).toBe("true");
    // The text survives in local storage for reload recovery.
    expect(JSON.parse(screen.getByTestId("stored").textContent ?? "[]"))
      .toMatchObject([{ content: "Hello offline" }]);
  } finally {
    vi.useRealTimers();
  }
});

it("restores the unsent submission after a reload and resends it on retry", async () => {
  fixture.session = completedServerSession();
  seedUnsentSubmission();
  fixture.connected = true;
  render(
    <ChatStateAdapterProvider>
      <Harness />
    </ChatStateAdapterProvider>,
  );
  await act(async () => {
    fireEvent.click(screen.getByText("Load"));
  });
  // The reloaded transcript reattaches the submission as clearly unsent.
  expect(readMessages()).toEqual([
    { role: "user", content: "hi", failed: false },
    { role: "assistant", content: "hello", failed: false },
    { role: "user", content: "Hello offline", failed: true },
  ]);
  expect(screen.getByTestId("submissionFailed").textContent).toBe("true");

  // Retry: the server transcript lacks the row, so it is resent as a new
  // turn from the stored snapshot (no duplicate user bubble).
  await act(async () => {
    fireEvent.click(screen.getByText("Resend"));
  });
  await vi.waitFor(() => {
    const start = fixture.sent.find(
      (message) => message.type === "start_turn",
    );
    expect(start).toMatchObject({ content: "Hello offline" });
  });
  // The turn completes: the server owns the transcript again and the
  // stored record is dropped.
  await act(async () => {
    fixture.emit?.({
      type: "done",
      source: "chat",
      stage: "responding",
      content: "",
      turn_id: "turn-retry",
      seq: 2,
      timestamp: Date.now() / 1000,
      metadata: {
        status: "completed",
        user_message_id: 3,
        assistant_message_id: 4,
      },
    });
  });
  expect(readStoredKeys()).toEqual([]);
  expect(screen.getByTestId("submissionFailed").textContent).toBe("false");
  const messages = readMessages();
  expect(messages[messages.length - 1]).toEqual({
    role: "assistant",
    content: "",
    failed: false,
  });
});

it("drops the record when the server transcript already holds the submission", async () => {
  const submissionId = seedUnsentSubmission();
  const serverHoldsIt = {
    ...completedServerSession(),
    status: "failed",
    messages: [
      ...completedServerSession().messages,
      {
        id: 3,
        session_id: "s1",
        role: "user",
        content: "Hello offline",
        metadata: { client_submission_id: submissionId },
        events: [],
        attachments: [],
        created_at: 3,
        parent_message_id: 2,
      },
    ],
  };
  fixture.session = serverHoldsIt;
  render(
    <ChatStateAdapterProvider>
      <Harness />
    </ChatStateAdapterProvider>,
  );
  await act(async () => {
    fireEvent.click(screen.getByText("Load"));
  });
  // The server persisted the user row before the stream broke, so its
  // transcript wins: no unsent duplicate is restored…
  expect(readMessages()).toEqual([
    { role: "user", content: "hi", failed: false },
    { role: "assistant", content: "hello", failed: false },
    { role: "user", content: "Hello offline", failed: false },
  ]);
  expect(screen.getByTestId("submissionFailed").textContent).toBe("false");
  // …and the local record is cleared.
  expect(readStoredKeys()).toEqual([]);
});

it("keeps a new unsent submission when an older server turn has identical text", async () => {
  vi.useFakeTimers();
  try {
    fixture.session = {
      ...completedServerSession(),
      messages: [
        ...completedServerSession().messages,
        {
          id: 3,
          session_id: "s1",
          role: "user",
          content: "Hello offline",
          events: [],
          attachments: [],
          created_at: 3,
          parent_message_id: 2,
        },
      ],
    };
    const firstView = render(
      <ChatStateAdapterProvider>
        <Harness />
      </ChatStateAdapterProvider>,
    );
    await act(async () => {
      fireEvent.click(screen.getByText("Load"));
    });
    fireEvent.click(screen.getByText("Send"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_400);
    });
    const saved = readFailedSubmission("s1");
    expect(saved?.submissionId).toBeTruthy();
    firstView.unmount();
    render(
      <ChatStateAdapterProvider>
        <Harness />
      </ChatStateAdapterProvider>,
    );
    await act(async () => {
      fireEvent.click(screen.getByText("Load"));
    });
    expect(readMessages().slice(-2)).toEqual([
      { role: "user", content: "Hello offline", failed: false },
      { role: "user", content: "Hello offline", failed: true },
    ]);
    expect(readStoredKeys()).toEqual(["s1"]);
  } finally {
    vi.useRealTimers();
  }
});

it("preserves text after storage quota errors without offering an incomplete resend", async () => {
  const localSetItem = vi.spyOn(localStorage, "setItem").mockImplementation(() => {
    throw new DOMException("Storage quota exceeded", "QuotaExceededError");
  });
  const sessionSetItem = sessionStorage.setItem.bind(sessionStorage);
  vi.spyOn(sessionStorage, "setItem").mockImplementation((key, value) => {
    if (value.length > 500) {
      throw new DOMException("Storage quota exceeded", "QuotaExceededError");
    }
    sessionSetItem(key, value);
  });
  fixture.session = completedServerSession();
  storeFailedSubmission("s1", {
    content: "Text with attachment",
    capability: "chat",
    priorMatchingUserIds: [],
    requestSnapshot: {
      content: "Text with attachment",
      capability: "chat",
      language: "en",
      attachments: [{ filename: "large.png", base64: "A".repeat(10_000) }],
    },
  });
  const saved = readFailedSubmission("s1");
  expect(saved?.content).toBe("Text with attachment");
  expect(saved?.retryRequiresReview).toBe(true);
  expect(JSON.stringify(saved?.requestSnapshot)).not.toContain("large.png");
  expect(localSetItem).toHaveBeenCalled();
  render(
    <ChatStateAdapterProvider>
      <Harness />
    </ChatStateAdapterProvider>,
  );
  await act(async () => {
    fireEvent.click(screen.getByText("Load"));
  });
  expect(readMessages().at(-1)).toEqual({
    role: "user",
    content: "Text with attachment",
    failed: true,
  });
  expect(screen.getByTestId("submissionNeedsReview").textContent).toBe("true");
  expect(screen.getByTestId("lastTurnFailed").textContent).toBe("false");
});

it("restores a failed first message in a draft and can retry after reload", async () => {
  vi.useFakeTimers();
  try {
    fixture.session = undefined;
    const firstView = render(
      <ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>,
    );
    fireEvent.click(screen.getByText("Send"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_400);
    });
    expect(readMessages()).toEqual([
      { role: "user", content: "Hello offline", failed: true },
    ]);
    expect(readFailedSubmissions("draft:general")).toHaveLength(1);
    firstView.unmount();

    fixture.connected = true;
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    expect(readMessages()).toEqual([
      { role: "user", content: "Hello offline", failed: true },
    ]);
    expect(screen.getByTestId("lastTurnFailed").textContent).toBe("true");
    await act(async () => {
      fireEvent.click(screen.getByText("Resend"));
    });
    expect(fixture.sent.at(-1)).toMatchObject({
      type: "start_turn",
      content: "Hello offline",
      session_id: null,
    });
    await act(async () => {
      fixture.emit?.({
        type: "session", source: "chat", stage: "", content: "",
        turn_id: "draft-retry", seq: 0, timestamp: Date.now() / 1000,
        metadata: { session_id: "new-session", turn_id: "draft-retry" },
      });
      fixture.emit?.({
        type: "done", source: "chat", stage: "responding", content: "",
        turn_id: "draft-retry", seq: 1, timestamp: Date.now() / 1000,
        metadata: { status: "completed", user_message_id: 1, assistant_message_id: 2 },
      });
    });
    expect(readFailedSubmissions("draft:general")).toEqual([]);
  } finally {
    vi.useRealTimers();
  }
});

it("retries a failed draft with its original settings after live settings change", async () => {
  vi.useFakeTimers();
  try {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Send"));
    await act(async () => { await vi.advanceTimersByTimeAsync(2_400); });
    fireEvent.click(screen.getByText("Change live settings"));
    fixture.connected = true;
    await act(async () => { fireEvent.click(screen.getByText("Resend")); });
    expect(fixture.sent.at(-1)).toMatchObject({
      type: "start_turn", content: "Hello offline", capability: null,
      workspace_mode: "", workspace_id: null, course_id: null,
      mastery_path_id: null, mastery_session_mode: null, persona: "",
      llm_selection: null, language: "en", reading_workspace_id: null,
      reading_material_id: null, timed_media_id: null,
    });
    expect(fixture.sent.at(-1)).not.toHaveProperty("reply_language_override");
  } finally {
    vi.useRealTimers();
  }
});

it("retries the original reading viewport after the live document changes", async () => {
  vi.useFakeTimers();
  try {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Prepare reading"));
    fireEvent.click(screen.getByText("Send"));
    await act(async () => { await vi.advanceTimersByTimeAsync(2_400); });
    setReadingWorkspace("ws-other");
    setReadingMaterial("feedface", 3);
    setReadingViewport({ locator: 99, selection: "new passage", timeSeconds: 33 });
    fixture.connected = true;
    await act(async () => { fireEvent.click(screen.getByText("Resend")); });
    expect(fixture.sent.at(-1)).toMatchObject({
      type: "start_turn", workspace_id: "ws-reading",
      reading_workspace_id: "ws-reading", reading_material_id: "deadbeef",
      reading_material_revision: 2,
      reading_viewport: { locator: 7, selection: "old passage", time_seconds: 12 },
    });
  } finally {
    vi.useRealTimers();
  }
});

it("retries the original watching position after the live video changes", async () => {
  vi.useFakeTimers();
  try {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Prepare watching"));
    fireEvent.click(screen.getByText("Send"));
    await act(async () => { await vi.advanceTimersByTimeAsync(2_400); });
    setWatchingMaterial("video-b");
    setWatchingViewport(99);
    fixture.connected = true;
    await act(async () => { fireEvent.click(screen.getByText("Resend")); });
    expect(fixture.sent.at(-1)).toMatchObject({
      type: "start_turn", timed_media_id: "video-a",
      timed_media_viewport: { time_seconds: 42 },
    });
  } finally {
    vi.useRealTimers();
  }
});

it("Stop before admission cannot erase another tab's newer same-ID retry", async () => {
  vi.useFakeTimers();
  try {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Send"));
    const original = readFailedSubmission("draft:general");
    expect(original?.submissionId).toBeTruthy();
    await vi.advanceTimersByTimeAsync(1);
    // Tab A still has the failed logical submission and rewrites it while
    // this tab's socket has no turn ID. The Stop action must not delete A's
    // newer durable record.
    storeFailedSubmission("draft:general", {
      submissionId: original?.submissionId,
      content: original?.content ?? "",
      capability: original?.capability,
      requestSnapshot: original?.requestSnapshot,
    });
    fireEvent.click(screen.getByText("Stop"));
    expect(readFailedSubmission("draft:general")?.submissionId)
      .toBe(original?.submissionId);
    expect(screen.getByTestId("submissionFailed").textContent).toBe("true");
  } finally {
    vi.useRealTimers();
  }
});

it("hydrates an already selected empty draft after the chat page's child effect", () => {
  storeFailedSubmission("draft:general", {
    content: "First message offline",
    requestSnapshot: {
      content: "First message offline", capability: "chat",
      enabledTools: [], knowledgeBases: [], language: "en",
    },
  });
  render(
    <StrictMode>
      <ChatStateAdapterProvider>
        <BootstrapDraft />
        <Harness />
      </ChatStateAdapterProvider>
    </StrictMode>,
  );
  expect(readMessages()).toEqual([
    { role: "user", content: "First message offline", failed: true },
  ]);
  expect(screen.getByTestId("capability").textContent).toBe("deep_research");
  expect(screen.getByTestId("lastTurnFailed").textContent).toBe("true");
});

it("restores the failed draft when /chat remounts under the same provider", () => {
  storeFailedSubmission("draft:general", {
    content: "First message offline",
    requestSnapshot: {
      content: "First message offline", capability: "chat",
      enabledTools: [], knowledgeBases: [], language: "en",
    },
  });
  render(<PersistentProviderRoutes />);
  expect(readMessages().at(-1)?.content).toBe("First message offline");
  fireEvent.click(screen.getByText("Toggle chat route"));
  fireEvent.click(screen.getByText("Toggle chat route"));
  expect(readMessages().at(-1)).toEqual({
    role: "user", content: "First message offline", failed: true,
  });
  expect(screen.getByTestId("capability").textContent).toBe("deep_research");
});

it("keeps a start_turn_rejected submission as an unsent user row across reload", async () => {
  fixture.connected = true;
  fixture.session = completedServerSession();
  const firstView = render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
  await act(async () => { fireEvent.click(screen.getByText("Load")); });
  fireEvent.click(screen.getByText("Send"));
  await act(async () => {
    fixture.emit?.({
      type: "error", source: "transport", stage: "", content: "Turn rejected",
      timestamp: Date.now() / 1000,
      metadata: { reason: "start_turn_rejected", turn_terminal: true, status: "failed" },
    });
  });
  expect(readMessages().at(-1)).toEqual({
    role: "user", content: "Hello offline", failed: true,
  });
  expect(readFailedSubmissions("s1")).toHaveLength(1);
  firstView.unmount();
  render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
  await act(async () => { fireEvent.click(screen.getByText("Load")); });
  expect(readMessages().at(-1)).toEqual({
    role: "user", content: "Hello offline", failed: true,
  });
  expect(screen.getByTestId("lastTurnFailed").textContent).toBe("true");
});

it("keeps both unsent messages when a second direct send fails", async () => {
  vi.useFakeTimers();
  try {
    fixture.session = completedServerSession();
    const firstView = render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    await act(async () => { fireEvent.click(screen.getByText("Load")); });
    fireEvent.click(screen.getByText("Send"));
    await act(async () => { await vi.advanceTimersByTimeAsync(2_400); });
    fireEvent.click(screen.getByText("Send another"));
    await act(async () => { await vi.advanceTimersByTimeAsync(2_400); });
    expect(readFailedSubmissions("s1").map((record) => record.content)).toEqual([
      "Hello offline", "Second offline",
    ]);
    firstView.unmount();
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    await act(async () => { fireEvent.click(screen.getByText("Load")); });
    expect(readMessages().slice(-2)).toEqual([
      { role: "user", content: "Hello offline", failed: true },
      { role: "user", content: "Second offline", failed: true },
    ]);
    expect(screen.getByTestId("lastTurnFailed").textContent).toBe("true");
  } finally {
    vi.useRealTimers();
  }
});

it("a later successful send clears only its own record", async () => {
  vi.useFakeTimers();
  try {
    fixture.session = completedServerSession();
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    await act(async () => { fireEvent.click(screen.getByText("Load")); });
    fireEvent.click(screen.getByText("Send"));
    await act(async () => { await vi.advanceTimersByTimeAsync(2_400); });
    fixture.connected = true;
    fireEvent.click(screen.getByText("Send another"));
    expect(readFailedSubmissions("s1")).toHaveLength(2);
    await act(async () => {
      fixture.emit?.({
        type: "done", source: "chat", stage: "responding", content: "",
        turn_id: "second-turn", seq: 2, timestamp: Date.now() / 1000,
        metadata: { status: "completed", user_message_id: 3, assistant_message_id: 4 },
      });
    });
    expect(readFailedSubmissions("s1").map((record) => record.content)).toEqual([
      "Hello offline",
    ]);
  } finally {
    vi.useRealTimers();
  }
});

it("moves an older failed draft message into the server session after a later send succeeds", async () => {
  vi.useFakeTimers();
  try {
    const firstView = render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Send"));
    await act(async () => { await vi.advanceTimersByTimeAsync(2_400); });
    fixture.connected = true;
    fireEvent.click(screen.getByText("Send another"));
    const secondId = readFailedSubmissions("draft:general").at(-1)?.submissionId;
    await act(async () => {
      fixture.emit?.({
        type: "session", source: "chat", stage: "", content: "",
        turn_id: "second-draft-turn", seq: 0, timestamp: Date.now() / 1000,
        metadata: { session_id: "new-session", turn_id: "second-draft-turn" },
      });
    });
    expect(readFailedSubmissions("draft:general")).toEqual([]);
    expect(readFailedSubmissions("new-session")).toHaveLength(2);
    await act(async () => {
      fixture.emit?.({
        type: "done", source: "chat", stage: "responding", content: "",
        turn_id: "second-draft-turn", seq: 1, timestamp: Date.now() / 1000,
        metadata: { status: "completed", user_message_id: 3, assistant_message_id: 4 },
      });
    });
    expect(readFailedSubmissions("new-session").map((record) => record.content)).toEqual([
      "Hello offline",
    ]);
    firstView.unmount();
    fixture.session = {
      ...completedServerSession(),
      messages: [
        ...completedServerSession().messages,
        {
          id: 3, session_id: "new-session", role: "user", content: "Second offline",
          metadata: { client_submission_id: secondId },
          events: [], attachments: [], created_at: 3, parent_message_id: 2,
        },
      ],
    };
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    await act(async () => { fireEvent.click(screen.getByText("Load new")); });
    expect(readMessages().at(-1)).toEqual({
      role: "user", content: "Hello offline", failed: true,
    });
  } finally {
    vi.useRealTimers();
  }
});

it("does not mistake another tab's identical text for this submission", async () => {
  const ownId = seedUnsentSubmission();
  fixture.session = {
    ...completedServerSession(),
    messages: [
      ...completedServerSession().messages,
      {
        id: 3, session_id: "s1", role: "user", content: "Hello offline",
        metadata: { client_submission_id: "other-tab-submission" },
        events: [], attachments: [], created_at: 3, parent_message_id: 2,
      },
    ],
  };
  const firstView = render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
  await act(async () => { fireEvent.click(screen.getByText("Load")); });
  expect(readMessages().at(-1)).toEqual({
    role: "user", content: "Hello offline", failed: true,
  });
  expect(readFailedSubmissions("s1")).toHaveLength(1);
  fixture.connected = true;
  await act(async () => { fireEvent.click(screen.getByText("Resend")); });
  expect(fixture.sent.at(-1)).toMatchObject({
    type: "start_turn", content: "Hello offline", client_submission_id: ownId,
  });
  expect(fixture.sent.some((command) => command.type === "regenerate")).toBe(false);
  firstView.unmount();
  (fixture.session.messages as Array<Record<string, unknown>>)[2].metadata = {
    client_submission_id: ownId,
  };
  render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
  await act(async () => { fireEvent.click(screen.getByText("Load")); });
  expect(readMessages().at(-1)).toEqual({
    role: "user", content: "Hello offline", failed: false,
  });
  expect(readFailedSubmissions("s1")).toEqual([]);
});

it("falls back to localStorage text when sessionStorage is unavailable", () => {
  const localSetItem = localStorage.setItem.bind(localStorage);
  vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (value.length > 500) throw new DOMException("Quota", "QuotaExceededError");
    localSetItem(key, value);
  });
  vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
    throw new DOMException("Unavailable", "SecurityError");
  });
  storeFailedSubmission("s1", {
    content: "Keep this text", capability: "chat",
    requestSnapshot: {
      content: "Keep this text", language: "en",
      attachments: [{ filename: "huge.png", base64: "A".repeat(10_000) }],
    },
  });
  const record = readFailedSubmission("s1");
  expect(record?.content).toBe("Keep this text");
  expect(record?.retryRequiresReview).toBe(true);
  expect(localStorage.getItem(
    "deeptutor.failedSubmissions.record.s1:" + record?.submissionId,
  )).toContain("Keep this text");
});

it("keeps the old session fallback's precedence, including an empty tombstone", () => {
  const old = {
    submissionId: "old-map", content: "Stale map text", capability: "chat",
    requestSnapshot: { content: "Stale map text" }, savedAt: Date.now(),
  };
  localStorage.setItem("deeptutor.failedSubmissions", JSON.stringify({ s1: [old] }));
  sessionStorage.setItem("deeptutor.failedSubmissions.fallback.s1", "[]");
  expect(readFailedSubmissions("s1")).toEqual([]);
  sessionStorage.setItem("deeptutor.failedSubmissions.fallback.s1", JSON.stringify([{
    ...old, submissionId: "fallback", content: "Fallback text",
  }]));
  expect(readFailedSubmissions("s1").map((record) => record.content)).toEqual([
    "Fallback text",
  ]);
});

it("saves to localStorage when the sessionStorage getter itself throws", () => {
  vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
    throw new DOMException("Unavailable", "SecurityError");
  });
  expect(storeFailedSubmission("s1", {
    content: "Local survives", requestSnapshot: { content: "Local survives" },
  })).not.toBeNull();
  expect(readFailedSubmission("s1")?.content).toBe("Local survives");
});

it("prunes expired records across sessions before falling back on quota", () => {
  const staleKey = "deeptutor.failedSubmissions.record.old:stale";
  localStorage.setItem(staleKey, JSON.stringify({
    submissionId: "stale", content: "Old attachment", capability: "chat",
    requestSnapshot: { content: "Old attachment", attachment: "A".repeat(10_000) },
    savedAt: Date.now() - 8 * 24 * 60 * 60 * 1000,
  }));
  const localSetItem = localStorage.setItem.bind(localStorage);
  vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (key.startsWith("deeptutor.failedSubmissions.record.") &&
        localStorage.getItem(staleKey)) {
      throw new DOMException("Quota", "QuotaExceededError");
    }
    localSetItem(key, value);
  });
  expect(storeFailedSubmission("s1", {
    content: "New text", requestSnapshot: { content: "New text" },
  })).not.toBeNull();
  expect(localStorage.getItem(staleKey)).toBeNull();
  expect(readFailedSubmission("s1")?.content).toBe("New text");
});

it("prefers a newer full local snapshot when stale session removal fails", () => {
  vi.useFakeTimers();
  try {
    vi.setSystemTime(new Date("2026-09-27T04:00:00Z"));
    const localSetItem = localStorage.setItem.bind(localStorage);
    let fullFits = false;
    vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
      if (!fullFits && value.length > 500) {
        throw new DOMException("Quota", "QuotaExceededError");
      }
      localSetItem(key, value);
    });
    storeFailedSubmission("s1", {
      submissionId: "same-id", content: "Old text", capability: "chat",
      requestSnapshot: { content: "Old text", attachment: "A".repeat(10_000) },
    });
    fullFits = true;
    vi.spyOn(sessionStorage, "removeItem").mockImplementation(() => {
      throw new DOMException("Unavailable", "SecurityError");
    });
    storeFailedSubmission("s1", {
      submissionId: "same-id", content: "New text", capability: "chat",
      requestSnapshot: { content: "New text", attachment: "B".repeat(10_000) },
    });
    expect(readFailedSubmission("s1")?.content).toBe("New text");
    expect(readFailedSubmission("s1")?.requestSnapshot).toMatchObject({
      attachment: "B".repeat(10_000),
    });
  } finally {
    vi.useRealTimers();
  }
});

it("binds a failed draft to its server session when no destination copy fits", () => {
  storeFailedSubmission("draft:general", {
    submissionId: "draft-a", content: "Full draft", capability: "chat",
    requestSnapshot: { content: "Full draft", attachment: "A".repeat(10_000) },
  });
  const sourceKey = "deeptutor.failedSubmissions.record.draft%3Ageneral:draft-a";
  const localSetItem = localStorage.setItem.bind(localStorage);
  vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (key.startsWith("deeptutor.failedSubmissions.record.s2:")) {
      throw new DOMException("Quota", "QuotaExceededError");
    }
    localSetItem(key, value);
  });
  const sessionSetItem = sessionStorage.setItem.bind(sessionStorage);
  vi.spyOn(sessionStorage, "setItem").mockImplementation((key, value) => {
    if (key.startsWith("deeptutor.failedSubmissions.record.s2:")) {
      throw new DOMException("Quota", "QuotaExceededError");
    }
    sessionSetItem(key, value);
  });
  expect(moveFailedSubmissions("draft:general", "s2", ["draft-a"])).toEqual(["draft-a"]);
  expect(localStorage.getItem(sourceKey)).toContain("Full draft");
  expect(readFailedSubmissions("s2").map((record) => record.content)).toEqual(["Full draft"]);
  expect(readFailedSubmissions("draft:general")).toEqual([]);
  sessionStorage.clear(); // Closing the tab removes the binding, not the durable source.
  expect(readFailedSubmissions("draft:general").map((record) => record.content)).toEqual([
    "Full draft",
  ]);
});

it("keeps the durable draft source when its destination only fits in sessionStorage", () => {
  storeFailedSubmission("draft:general", {
    submissionId: "draft-a", content: "Full draft", capability: "chat",
    requestSnapshot: { content: "Full draft", attachment: "A".repeat(10_000) },
  });
  const localSetItem = localStorage.setItem.bind(localStorage);
  vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (key.startsWith("deeptutor.failedSubmissions.record.s2:")) {
      throw new DOMException("Quota", "QuotaExceededError");
    }
    localSetItem(key, value);
  });
  expect(moveFailedSubmissions("draft:general", "s2", ["draft-a"])).toEqual(["draft-a"]);
  expect(readFailedSubmission("s2")?.requestSnapshot).toMatchObject({
    attachment: expect.any(String),
  });
  sessionStorage.clear();
  expect(readFailedSubmission("draft:general")?.content).toBe("Full draft");
});

it("clears the bound draft source once the server accepts its submission", () => {
  storeFailedSubmission("draft:general", {
    submissionId: "draft-a", content: "Full draft", capability: "chat",
    requestSnapshot: { content: "Full draft" },
  });
  const localSetItem = localStorage.setItem.bind(localStorage);
  vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (key.startsWith("deeptutor.failedSubmissions.record.s2:")) {
      throw new DOMException("Quota", "QuotaExceededError");
    }
    localSetItem(key, value);
  });
  moveFailedSubmissions("draft:general", "s2", ["draft-a"]);
  clearFailedSubmission("s2", "draft-a");
  expect(readFailedSubmissions("s2")).toEqual([]);
  expect(readFailedSubmissions("draft:general")).toEqual([]);
  expect(localStorage.getItem(
    "deeptutor.failedSubmissions.record.draft%3Ageneral:draft-a",
  )).toBeNull();
});

it("warns when browser storage cannot save even the unsent text", async () => {
  vi.useFakeTimers();
  try {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("Quota", "QuotaExceededError");
    });
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
      throw new DOMException("Unavailable", "SecurityError");
    });
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Send"));
    await act(async () => { await vi.advanceTimersByTimeAsync(2_400); });
    expect(screen.getByTestId("submissionNotSaved").textContent).toBe("true");
    expect(screen.getByTestId("submissionFailed").textContent).toBe("true");
    expect(readMessages().at(-1)?.content).toBe("Hello offline");
    expect(readFailedSubmissions("draft:general")).toEqual([]);
  } finally {
    vi.useRealTimers();
  }
});

it("unions one tab's session fallback with another tab's local record", () => {
  const localSetItem = localStorage.setItem.bind(localStorage);
  vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (value.length > 500) throw new DOMException("Quota", "QuotaExceededError");
    localSetItem(key, value);
  });
  storeFailedSubmission("s1", {
    submissionId: "large-tab-a", content: "Tab A attachment", capability: "chat",
    requestSnapshot: {
      content: "Tab A attachment", language: "en",
      attachments: [{ filename: "large.png", base64: "A".repeat(10_000) }],
    },
  });
  expect(sessionStorage.getItem(
    "deeptutor.failedSubmissions.record.s1:large-tab-a",
  )).toContain("Tab A attachment");
  storeFailedSubmission("s1", {
    submissionId: "small-tab-b", content: "Tab B text", capability: "chat",
    requestSnapshot: { content: "Tab B text", language: "en" },
  });
  expect(readFailedSubmissions("s1").map((record) => record.content).sort()).toEqual([
    "Tab A attachment", "Tab B text",
  ]);
  clearFailedSubmission("s1", "large-tab-a");
  expect(readFailedSubmissions("s1").map((record) => record.content)).toEqual([
    "Tab B text",
  ]);
});

it("preserves an interleaved write from another tab while storing and clearing", () => {
  const localSetItem = localStorage.setItem.bind(localStorage);
  let interleaved = false;
  vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (!interleaved && key === "deeptutor.failedSubmissions.record.s1:tab-a") {
      interleaved = true;
      // Tab B writes after A has prepared its value but before A commits.
      localSetItem("deeptutor.failedSubmissions.record.s2:tab-b", JSON.stringify({
        submissionId: "tab-b", content: "Tab B pending", capability: "chat",
        requestSnapshot: { content: "Tab B pending", language: "en" },
        savedAt: Date.now(),
      }));
    }
    localSetItem(key, value);
  });
  storeFailedSubmission("s1", {
    submissionId: "tab-a", content: "Tab A pending", capability: "chat",
    requestSnapshot: { content: "Tab A pending", language: "en" },
  });
  expect(interleaved).toBe(true);
  expect(readFailedSubmissions("s1").map((record) => record.content)).toEqual(["Tab A pending"]);
  expect(readFailedSubmissions("s2").map((record) => record.content)).toEqual(["Tab B pending"]);
  const localRemoveItem = localStorage.removeItem.bind(localStorage);
  let interleavedClear = false;
  vi.spyOn(localStorage, "removeItem").mockImplementation((key) => {
    if (!interleavedClear && key === "deeptutor.failedSubmissions.record.s1:tab-a") {
      interleavedClear = true;
      localSetItem("deeptutor.failedSubmissions.record.s2:tab-c", JSON.stringify({
        submissionId: "tab-c", content: "Tab C pending", capability: "chat",
        requestSnapshot: { content: "Tab C pending", language: "en" },
        savedAt: Date.now(),
      }));
    }
    localRemoveItem(key);
  });
  clearFailedSubmission("s1", "tab-a");
  expect(interleavedClear).toBe(true);
  expect(readFailedSubmissions("s2").map((record) => record.content)).toEqual([
    "Tab B pending", "Tab C pending",
  ]);
});

it("keeps a stale tab's retry after another tab cleared the same submission ID", () => {
  vi.useFakeTimers();
  try {
    vi.setSystemTime(new Date("2026-09-27T04:00:00Z"));
    storeFailedSubmission("s1", {
      submissionId: "shared-id", content: "First try", capability: "chat",
      requestSnapshot: { content: "First try" },
    });
    // Tab B receives the server acknowledgment while tab A still has its
    // optimistic failed row and retries that same causal ID offline.
    clearFailedSubmission("s1", "shared-id");
    storeFailedSubmission("s1", {
      submissionId: "shared-id", content: "First try", capability: "chat",
      requestSnapshot: { content: "First try" },
    });
    expect(readFailedSubmissions("s1").map((record) => record.content)).toEqual([
      "First try",
    ]);
    clearFailedSubmission("s1", "shared-id");
    expect(readFailedSubmissions("s1")).toEqual([]);
  } finally {
    vi.useRealTimers();
  }
});
