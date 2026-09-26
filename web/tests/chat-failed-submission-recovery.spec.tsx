import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { initI18n } from "@/i18n/init";
import { storeFailedSubmission } from "@/lib/failed-submissions";

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
  storeFailedSubmission("s1", {
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
      <button onClick={() => void resendLastMessage()}>Resend</button>
      <div data-testid="submissionFailed">
        {String(state.submissionFailed)}
      </div>
      <div data-testid="lastTurnFailed">{String(state.lastTurnFailed)}</div>
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
  fixture.connected = false;
  fixture.sent = [];
  fixture.emit = undefined;
  fixture.close = undefined;
});

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
      .toMatchObject({ s1: { content: "Hello offline" } });
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
        events: [],
        attachments: [],
        created_at: 3,
        parent_message_id: 2,
      },
    ],
  };
  fixture.session = serverHoldsIt;
  seedUnsentSubmission();
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
