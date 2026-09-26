import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { initI18n } from "@/i18n/init";
import {
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
  const { state, sendMessage, resendLastMessage, loadSession } =
    useChatStateAdapter();
  return (
    <>
      <button onClick={() => void loadSession("s1")}>Load</button>
      <button onClick={() => sendMessage("Hello offline")}>Send</button>
      <button onClick={() => sendMessage("Second offline")}>Send another</button>
      <button onClick={() => void resendLastMessage()}>Resend</button>
      <div data-testid="submissionFailed">
        {String(state.submissionFailed)}
      </div>
      <div data-testid="lastTurnFailed">{String(state.lastTurnFailed)}</div>
      <div data-testid="submissionNeedsReview">{String(state.submissionNeedsReview)}</div>
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
        {localStorage.getItem("deeptutor.failedSubmissions") ?? ""}
      </div>
    </>
  );
}

function readMessages() {
  return JSON.parse(
    screen.getByTestId("messages").textContent ?? "[]",
  ) as Array<{ role: string; content: string; failed: boolean }>;
}

function readStoredKeys() {
  return Object.keys(
    JSON.parse(screen.getByTestId("stored").textContent || "{}"),
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
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
    expect(JSON.parse(screen.getByTestId("stored").textContent ?? "{}"))
      .toMatchObject({ s1: [{ content: "Hello offline" }] });
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
  expect(localStorage.getItem("deeptutor.failedSubmissions")).toContain("Keep this text");
});
