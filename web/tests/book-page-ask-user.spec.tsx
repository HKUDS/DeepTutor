import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import BookChatPanel from "@/app/(workspace)/learning/books/components/BookChatPanel";
import type { StreamEvent } from "@/features/chat/model/protocol";
import type { Book, Page } from "@/lib/book-types";
import { COMMAND_CONFIRMATION_FAILED } from "@/features/chat/transport/command-delivery";
import { REPLY_NOT_DELIVERED } from "@/lib/ask-user-state";

const fixture = vi.hoisted(() => ({
  emit: undefined as ((event: StreamEvent) => void) | undefined,
  send: vi.fn(),
  sendAwaitingAck: vi.fn(),
  disconnect: vi.fn(),
  getSession: vi.fn(),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/context/AppShellContext", () => ({ useAppShell: () => ({ language: "en" }) }));
vi.mock("@/lib/attachment-limits", () => ({ useAttachmentLimits: () => ({}) }));
vi.mock("@/components/common/AssistantResponse", () => ({
  default: ({ content }: { content: string }) => <div>{content}</div>,
}));
vi.mock("@/components/common/InlineMarkdown", () => ({
  default: ({ content }: { content: string }) => <span>{content}</span>,
}));
vi.mock("@/shared/ui/Tooltip", () => ({
  default: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/lib/session-api", () => ({ getSession: fixture.getSession }));
vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: class {
    connected = true;
    constructor(emit: (event: StreamEvent) => void) { fixture.emit = emit; }
    connect() {}
    disconnect = fixture.disconnect;
    send = fixture.send;
    sendAwaitingAck = fixture.sendAwaitingAck;
  },
}));

const book = { id: "book", language: "en", knowledge_bases: [] } as unknown as Book;
const page = { id: "page", title: "Chapter" } as Page;
const question = {
  intro: null,
  questions: [{
    id: "meaning", prompt: "What would you like explained?", header: "Meaning",
    multi_select: false, allow_free_text: true, placeholder: null,
    options: [{ label: "This chapter", description: "Explain its main concepts." }],
  }],
};
function event(type: StreamEvent["type"], content = "", metadata = {}): StreamEvent {
  return { type, content, metadata, turn_id: "turn", session_id: "session", source: "chat", stage: "responding", timestamp: 0 };
}
const asked = event("tool_result", "", {
  tool_call_id: "ask-1", tool_metadata: { ask_user: question },
});
function emit(e: StreamEvent) { act(() => fixture.emit?.(e)); }
function sendQuestion() {
  const input = screen.getByPlaceholderText("Ask about this page…");
  fireEvent.change(input, { target: { value: "Explain this" } });
  fireEvent.submit(input.closest("form")!);
}
async function start() {
  const view = render(<BookChatPanel book={book} page={page} open onClose={() => {}} />);
  sendQuestion();
  await waitFor(() => expect(fixture.send).toHaveBeenCalled());
  emit(event("session", "", { session_id: "session" }));
  return view;
}
async function answer() {
  fireEvent.click(await screen.findByRole("button", { name: /This chapter/ }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Submit" })); });
}

beforeEach(() => {
  fixture.emit = undefined;
  fixture.send.mockReset();
  fixture.sendAwaitingAck.mockReset().mockResolvedValue(true);
  fixture.disconnect.mockReset();
  fixture.getSession.mockReset().mockResolvedValue({ messages: [], active_turns: [] });
});

it("renders a live question and submits answers to the same turn before continuing below it", async () => {
  await start();
  emit(event("content", "Before the question"));
  emit(asked);
  await answer();
  await waitFor(() => expect(fixture.sendAwaitingAck).toHaveBeenCalledWith(expect.objectContaining({
    type: "submit_user_reply", turn_id: "turn", text: "This chapter",
    answers: [{ questionId: "meaning", text: "This chapter" }],
  })));
  emit(event("progress", "", {
    ask_user_resolved: true, ask_user_tool_call_id: "ask-1",
    answers: [{ questionId: "meaning", text: "This chapter" }], assistant_content_offset: 19,
  }));
  emit(event("content", "After your answer"));
  emit(event("done"));
  expect(fixture.send.mock.calls.filter(([m]) => m.type === "start_turn")).toHaveLength(1);
  const before = screen.getByText("Before the question");
  const after = screen.getByText("After your answer");
  expect(before.compareDocumentPosition(screen.getByText("What would you like explained?")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText("What would you like explained?").compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("restores a waiting turn by replaying its events after a refresh", async () => {
  fixture.getSession.mockResolvedValue({
    messages: [{ role: "user", content: "Original question" }],
    active_turns: [{ id: "turn", turn_id: "turn", status: "waiting_input", last_seq: 5 }],
  });
  render(<BookChatPanel book={book} page={page} open onClose={() => {}} initialSessionId="session" />);
  await waitFor(() => expect(fixture.send).toHaveBeenCalledWith({ type: "subscribe_turn", turn_id: "turn", after_seq: 0 }));
  emit(asked);
  await answer();
  await waitFor(() => expect(fixture.sendAwaitingAck).toHaveBeenCalledWith(expect.objectContaining({ type: "submit_user_reply", turn_id: "turn" })));
  expect(screen.getAllByText("Original question")).toHaveLength(1);
});

it("keeps a rejected answer editable and allows a new message", async () => {
  fixture.sendAwaitingAck.mockResolvedValue(false);
  await start(); emit(asked); await answer();
  expect(await screen.findByText(REPLY_NOT_DELIVERED)).toBeVisible();
  expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
  sendQuestion();
  await waitFor(() => expect(fixture.send.mock.calls.filter(([m]) => m.type === "start_turn")).toHaveLength(2));
});

it("preserves an unconfirmed answer and reuses its command id when retried", async () => {
  fixture.sendAwaitingAck.mockRejectedValueOnce(new Error("lost acknowledgement"));
  await start(); emit(asked); await answer();
  expect(await screen.findByText(COMMAND_CONFIRMATION_FAILED)).toBeVisible();
  const first = fixture.sendAwaitingAck.mock.calls[0][0];
  expect(first.command_id).toBeTruthy();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Submit" })); });
  await waitFor(() => expect(fixture.sendAwaitingAck).toHaveBeenCalledTimes(2));
  expect(fixture.sendAwaitingAck.mock.calls[1][0].command_id).toBe(first.command_id);
});

it("does not resubscribe completed history or send its expired card to a later turn", async () => {
  fixture.getSession.mockResolvedValue({
    messages: [{ role: "assistant", content: "", events: [asked], metadata: { turn_id: "old-turn" } }],
    active_turns: [],
  });
  render(<BookChatPanel book={book} page={page} open onClose={() => {}} initialSessionId="session" />);
  await answer();
  expect(await screen.findByText(REPLY_NOT_DELIVERED)).toBeVisible();
  expect(fixture.send).not.toHaveBeenCalled();
  expect(fixture.sendAwaitingAck).not.toHaveBeenCalled();
});
