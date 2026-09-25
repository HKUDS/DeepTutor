import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  RESPONSE_LANGUAGE_EVENT,
  RESPONSE_LANGUAGE_STORAGE_KEY,
} from "@/context/app-shell-storage";
import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";

const mocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  updateReplyLanguage: vi.fn(),
  requests: [] as Record<string, unknown>[],
}));

vi.mock("@/lib/session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  getSession: mocks.getSession,
  updateSessionReplyLanguage: mocks.updateReplyLanguage,
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

const session = (replyLanguageOverride: string | null) => ({
  id: "session-1",
  session_id: "session-1",
  title: "Math",
  status: "completed",
  created_at: 1,
  updated_at: 1,
  messages: [],
  preferences: {
    language: "zh",
    reply_language_override: replyLanguageOverride,
  },
});

function Harness() {
  const { state, loadSession, setReplyLanguageOverride, sendMessage } = useChatStateAdapter();
  return (
    <>
      <button onClick={() => void loadSession("session-1")}>Load</button>
      <button onClick={() => void setReplyLanguageOverride("de").catch(() => undefined)}>Fix German</button>
      <button onClick={() => void setReplyLanguageOverride(null).catch(() => undefined)}>Use account</button>
      <button onClick={() => sendMessage("Explain this")}>Send</button>
      <output data-testid="session-language">
        {state.sessionId ?? "draft"}:{state.replyLanguageOverride ?? "account"}:{state.language}
      </output>
    </>
  );
}

const starts = () => mocks.requests.filter((request) => request.type === "start_turn");

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem(RESPONSE_LANGUAGE_STORAGE_KEY, "zh");
  mocks.requests.length = 0;
  mocks.getSession.mockReset().mockResolvedValue(session("fr"));
  mocks.updateReplyLanguage.mockReset().mockImplementation(async (_id, language) => session(language));
});

describe("conversation reply language", () => {
  it("loads a fixed language, ignores account changes, and clears to the current account default", async () => {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Load"));
    await waitFor(() => expect(screen.getByTestId("session-language")).toHaveTextContent("session-1:fr:fr"));

    localStorage.setItem(RESPONSE_LANGUAGE_STORAGE_KEY, "ja");
    act(() => window.dispatchEvent(new CustomEvent(RESPONSE_LANGUAGE_EVENT, { detail: { language: "ja" } })));
    expect(screen.getByTestId("session-language")).toHaveTextContent("session-1:fr:fr");
    fireEvent.click(screen.getByText("Send"));
    expect(starts()).toHaveLength(1);
    expect(starts()[0].language).toBe("fr");
    expect(starts()[0]).not.toHaveProperty("reply_language_override");

    fireEvent.click(screen.getByText("Use account"));
    await waitFor(() => expect(mocks.updateReplyLanguage).toHaveBeenCalledWith("session-1", null, undefined));
    await waitFor(() => expect(screen.getByTestId("session-language")).toHaveTextContent("session-1:account:ja"));
  });

  it("persists a new draft's choice with the first turn", async () => {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Fix German"));
    await waitFor(() => expect(screen.getByTestId("session-language")).toHaveTextContent("draft:de:de"));
    fireEvent.click(screen.getByText("Send"));
    expect(starts()).toHaveLength(1);
    expect(starts()[0]).toMatchObject({ language: "de", reply_language_override: "de" });
    expect(mocks.updateReplyLanguage).not.toHaveBeenCalled();
  });

  it("keeps the saved selector when changing an existing conversation fails", async () => {
    mocks.updateReplyLanguage.mockRejectedValue(new Error("Save failed"));
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Load"));
    await waitFor(() => expect(screen.getByTestId("session-language")).toHaveTextContent("session-1:fr:fr"));
    fireEvent.click(screen.getByText("Fix German"));
    await waitFor(() => expect(mocks.updateReplyLanguage).toHaveBeenCalled());
    expect(screen.getByTestId("session-language")).toHaveTextContent("session-1:fr:fr");
  });
});
