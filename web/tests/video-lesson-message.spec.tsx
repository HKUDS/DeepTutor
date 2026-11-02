import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatStateAdapterProvider, useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { AssistantMessage } from "@/features/chat/messages/ChatMessageList";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { compactTracePreview } from "@/features/chat/trace/memory";
import { initI18n } from "@/i18n/init";

initI18n("en");
const transport = vi.hoisted(() => ({ emit: undefined as undefined | ((e: StreamEvent) => void) }));
vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: class {
    connected = true;
    constructor(emit: typeof transport.emit) { transport.emit = emit; }
    connect() {}
    disconnect() {}
    send() {}
    setResumeState() {}
  },
}));
const summary = "Derivatives measure change; integrals measure accumulation.";
const url = "/files/outputs/workspace/chat/video_lesson/turn-1/artifacts/lesson.html";
function event(type: StreamEvent["type"], seq: number, metadata = {}, content = ""): StreamEvent {
  return { type, seq, metadata, content, source: "video_lesson", stage: "render_output", timestamp: Date.now() / 1000,
    session_id: "session-1", turn_id: "turn-1" };
}
const result = event("result", 3, {
  title: "Calculus", response: summary,
  artifacts: [{ type: "html", url, filename: "lesson.html" }],
  code: { language: "tsx", content: "export const Lesson = () => null;" },
  render: { duration_seconds: 90, attempts: [{ stage: "done", errors: [] }] },
});
const done = event("done", 4, { status: "completed", user_message_id: 1, assistant_message_id: 2 });
function Harness() {
  const { state, sendMessage, regenerateLastMessage } = useChatStateAdapter();
  const msg = state.messages.at(-1);
  return <>
    <button onClick={() => sendMessage("Explain calculus", undefined, undefined, undefined, undefined,
      { capability: "video_lesson" })}>Generate lesson</button>
    <button onClick={() => regenerateLastMessage()}>Regenerate lesson</button>
    <output data-testid="session-capability">{state.activeCapability ?? "chat"}</output>
    <output data-testid="capability">{msg?.capability}</output>
    {msg?.role === "assistant" && <AssistantMessage msg={msg} isStreaming={state.isStreaming} />}
  </>;
}

describe("video lesson result delivery", () => {
  it("shows the player after a one-turn capability finishes in a normal chat", async () => {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Generate lesson"));
    await act(async () => {
      transport.emit?.(event("session", 1, { session_id: "session-1" }));
      transport.emit?.(event("content", 2, {}, summary));
      transport.emit?.(result);
      transport.emit?.(done);
    });
    expect(await screen.findByTitle("Calculus")).toHaveAttribute("src", expect.stringContaining(url));
    expect(screen.getByTestId("capability")).toHaveTextContent("video_lesson");
    expect(screen.getByTestId("session-capability")).toHaveTextContent("chat");
    fireEvent.click(screen.getByText("Regenerate lesson"));
    expect(screen.getByTestId("capability")).toHaveTextContent("video_lesson");
  });

  it("restores the player from the persisted result preview", async () => {
    const events = compactTracePreview([event("content", 2, {}, summary), result, done]).events;
    render(<AssistantMessage msg={{ capability: "video_lesson", content: summary, events }} isStreaming={false} />);
    expect(await screen.findByTitle("Calculus")).toHaveAttribute("src", expect.stringContaining(url));
  });

  it("recognizes an authoritative video result when the message still has the chat capability", async () => {
    render(<AssistantMessage msg={{ capability: "chat", content: summary, events: [result, done] }} isStreaming={false} />);
    expect(await screen.findByTitle("Calculus")).toHaveAttribute("src", expect.stringContaining(url));
  });
  it("finds the playable result after an intermediate result without a page", async () => {
    render(<AssistantMessage msg={{ capability: "video_lesson", content: summary,
      events: [event("result", 1, { response: "Planning" }), result, done] }} isStreaming={false} />);
    expect(await screen.findByTitle("Calculus")).toHaveAttribute("src", expect.stringContaining(url));
  });

  it("does not turn an ordinary HTML artifact into a video player", () => {
    render(<AssistantMessage msg={{ capability: "chat", content: summary,
      events: [{ ...result, source: "chat" }, done] }} isStreaming={false} />);
    expect(screen.queryByTitle("Calculus")).toBeNull();
  });

  it("does not point an empty artifact URL back at the app", () => {
    render(<AssistantMessage msg={{ capability: "video_lesson", content: summary,
      events: [event("result", 3, { title: "Calculus", artifacts: [{ type: "html", url: " " }] }), done] }} isStreaming={false} />);
    expect(screen.queryByTitle("Calculus")).toBeNull();
  });

});
