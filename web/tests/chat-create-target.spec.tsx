import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";

const mocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  requests: [] as Record<string, unknown>[],
}));

vi.mock("@/lib/session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  getSession: mocks.getSession,
}));

vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: class {
    connected = true;
    connect() {}
    disconnect() {}
    setResumeState() {}
    send(message: Record<string, unknown>) {
      mocks.requests.push(message);
    }
  },
}));

const session = (createTarget: string | null) => ({
  id: "session-1",
  session_id: "session-1",
  title: "Authoring",
  status: "completed",
  created_at: 1,
  updated_at: 1,
  messages: [],
  preferences: {
    language: "en",
    create_target: createTarget ?? "",
  },
});

function Harness() {
  const { state, loadSession, setCreateTarget, sendMessage } = useChatStateAdapter();
  return (
    <>
      <button onClick={() => void loadSession("session-1")}>Load</button>
      <button onClick={() => setCreateTarget("skill")}>Author a skill</button>
      <button onClick={() => setCreateTarget(null)}>Leave create mode</button>
      <button onClick={() => sendMessage("hello")}>Send</button>
      <output data-testid="create-target">{state.createTarget ?? "none"}</output>
    </>
  );
}

const starts = () => mocks.requests.filter((request) => request.type === "start_turn");

beforeEach(() => {
  mocks.requests.length = 0;
  mocks.getSession.mockReset().mockResolvedValue(session("skill"));
});

describe("create mode state", () => {
  it("restores the chip from the session's preferences, '' becoming null", async () => {
    mocks.getSession.mockResolvedValue(session(null));
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Load"));
    await waitFor(() => expect(screen.getByTestId("create-target")).toHaveTextContent("none"));
  });

  it("restores a non-empty kind from preferences and sends it on every turn", async () => {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Load"));
    await waitFor(() => expect(screen.getByTestId("create-target")).toHaveTextContent("skill"));
    fireEvent.click(screen.getByText("Send"));
    expect(starts()).toHaveLength(1);
    expect(starts()[0].create_target).toBe("skill");
  });

  it("sends create_target: null once the chip is removed, and never omits the key", async () => {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    act(() => fireEvent.click(screen.getByText("Send")));
    expect(starts()).toHaveLength(1);
    expect(starts()[0].create_target).toBe(null);
    expect("create_target" in starts()[0]).toBe(true);

    fireEvent.click(screen.getByText("Author a skill"));
    await waitFor(() => expect(screen.getByTestId("create-target")).toHaveTextContent("skill"));
    fireEvent.click(screen.getByText("Leave create mode"));
    await waitFor(() => expect(screen.getByTestId("create-target")).toHaveTextContent("none"));
    fireEvent.click(screen.getByText("Send"));
    expect(starts()).toHaveLength(2);
    expect(starts()[1].create_target).toBe(null);
  });
});
