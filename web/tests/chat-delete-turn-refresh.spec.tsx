import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";

const mocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  deleteMessage: vi.fn(),
  notifySessionsChanged: vi.fn(),
}));

vi.mock("@/lib/session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  getSession: mocks.getSession,
  deleteMessage: mocks.deleteMessage,
}));

vi.mock("@/lib/session-events", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session-events")>()),
  notifySessionsChanged: mocks.notifySessionsChanged,
}));

vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: class {
    connected = true;
    connect() {}
    disconnect() {}
    setResumeState() {}
    send() {}
  },
}));

const session = {
  id: "session-1",
  session_id: "session-1",
  title: "Why fork?",
  created_at: 1,
  updated_at: 1,
  status: "completed" as const,
  preferences: { language: "en" },
  messages: [
    { id: 1, session_id: "session-1", role: "user" as const, content: "Why?", events: [] },
    {
      id: 2,
      session_id: "session-1",
      role: "assistant" as const,
      content: "Because both processes continue.",
      events: [],
    },
  ],
};

function Harness() {
  const chat = useChatStateAdapter();
  const [detached, setDetached] = useState<string | null>(null);
  const [deletedIds, setDeletedIds] = useState<string | null>(null);

  useEffect(() => {
    void chat.loadSession("session-1");
    // The adapter owns the rest of the lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <button
        type="button"
        onClick={async () => {
          const result = await chat.deleteTurn(1);
          setDetached(result.detachedThreadIds.join(","));
          setDeletedIds(result.deletedMessageIds.join(","));
        }}
      >
        Delete turn
      </button>
      <output data-testid="detached">{detached ?? "none"}</output>
      <output data-testid="deleted-ids">{deletedIds ?? "none"}</output>
    </div>
  );
}

beforeEach(() => {
  mocks.getSession.mockReset().mockResolvedValue(session);
  mocks.deleteMessage.mockReset().mockResolvedValue({
    detachedThreadIds: ["thread-1", "thread-2"],
    deletedMessageIds: [1, 2],
  });
  mocks.notifySessionsChanged.mockReset();
});

it("returns detached thread ids and notifies every session-list subscriber", async () => {
  render(
    <ChatStateAdapterProvider>
      <Harness />
    </ChatStateAdapterProvider>,
  );

  await waitFor(() => expect(mocks.getSession.mock.calls[0]?.[0]).toBe("session-1"));
  await act(async () => {
    screen.getByRole("button", { name: "Delete turn" }).click();
  });

  await waitFor(() =>
    expect(screen.getByTestId("detached")).toHaveTextContent("thread-1,thread-2"),
  );
  expect(screen.getByTestId("deleted-ids")).toHaveTextContent("1,2");
  expect(mocks.deleteMessage).toHaveBeenCalledWith("session-1", 1);
  // useSessionThreads and the open side-chat panel both listen to this bus.
  expect(mocks.notifySessionsChanged).toHaveBeenCalledTimes(1);
});
