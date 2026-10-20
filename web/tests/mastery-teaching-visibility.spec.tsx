import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AssistantMessage } from "@/features/chat/messages/ChatMessageList";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { initI18n } from "@/i18n/init";

vi.mock("@/hooks/useVoiceAutoplay", () => ({
  useVoiceAutoplay: () => ({ autoplayEnabled: false }),
}));
// jsdom does not compute the CSS grid fold's zero-height clipping. Keep the real
// disclosure state and contents, substituting only its animated wrapper.
vi.mock("@/components/activity", async (original) => ({
  ...(await original<typeof import("@/components/activity")>()),
  ActivityFold: ({ open, children }: { open: boolean; children: React.ReactNode }) => <div hidden={!open}>{children}</div>,
}));
initI18n("en");

const lesson = "A filter lets some particles through and retains others. Its selectivity depends on particle size.";
const transition = "Apply that principle to a new example.";
const question = {
  question_id: "question-1",
  prompt: "Which particles pass through the filter?",
  question_type: "short",
  objective: { id: "objective-1", name: "Selective filters" },
  difficulty: "medium",
  attempt: 1,
  options: [],
  allow_free_text: true,
};

function event(type: StreamEvent["type"], content: string, metadata: Record<string, unknown> = {}): StreamEvent {
  return { type, content, metadata, source: "mastery_path", stage: "responding", timestamp: 1 } as StreamEvent;
}

function lessonEvents(reloaded: boolean, bookkeeping = "mastery_note_explained"): StreamEvent[] {
  const events = [
    event("content", lesson, { call_id: "round-1", call_kind: "agent_loop_round" }),
    event("tool_call", bookkeeping, { call_id: "note-1", tool_name: bookkeeping, assistant_content_offset: lesson.length }),
    event("tool_result", "Recorded", { call_id: "note-1", tool_name: bookkeeping }),
    event("thinking", "Internal assessment planning", { call_id: "round-2" }),
    event("content", transition, { call_id: "round-2", call_kind: "agent_loop_round" }),
    event("tool_call", "mastery_quiz", { call_id: "quiz-1", tool_name: "mastery_quiz", assistant_content_offset: (lesson + transition).length }),
    event("tool_result", "", { tool_call_id: "quiz-1", tool_metadata: { mastery_question: question } }),
    event("done", "", { status: "completed" }),
  ];
  // A persisted semantic preview uses offsets and authoritative message text,
  // without replaying every content delta or reasoning event.
  return reloaded ? events.filter((item) => item.type !== "content" && item.type !== "thinking") : events;
}

describe("Mastery teaching visibility", () => {
  it("keeps teaching visible while a quiz is pending and when the turn settles", async () => {
    const events = lessonEvents(false);
    const props = (trace: StreamEvent[], streaming: boolean) => ({
      msg: { content: lesson + transition, capability: "mastery_path", events: trace },
      isStreaming: streaming,
    });
    const view = render(<AssistantMessage {...props(events.slice(0, 5), true)} />);
    expect(screen.getByText(lesson)).toBeVisible();
    const pendingQuiz = [
      ...events.slice(0, 6),
      event("progress", "", { trace_kind: "call_status", call_state: "complete", call_role: "finish", call_id: "round-2" }),
    ];
    view.rerender(<AssistantMessage {...props(pendingQuiz, true)} />);
    expect(screen.getByText(lesson)).toBeVisible();
    expect(screen.getByText(transition)).toBeVisible();
    view.rerender(<AssistantMessage {...props(events, false)} />);
    expect(screen.getByText(lesson)).toBeVisible();
    expect(screen.getByText(transition)).toBeVisible();
    expect(await screen.findByText(question.prompt)).toBeVisible();
  });

  it("keeps a teaching-only turn visible after its final bookkeeping tool", async () => {
    const events = lessonEvents(false).slice(0, 3);
    render(<AssistantMessage msg={{ content: lesson, capability: "mastery_path", events }} />);
    expect(screen.getByText(lesson)).toBeVisible();
  });

  it.each([false, true])("keeps the lesson visible across bookkeeping (reloaded=%s)", async (reloaded) => {
    render(<AssistantMessage msg={{ content: lesson + transition, capability: "mastery_path", events: lessonEvents(reloaded) }} />);
    expect(screen.getByText(lesson)).toBeVisible();
    expect(screen.getByText(transition)).toBeVisible();
    expect(await screen.findByText(question.prompt)).toBeVisible();
    const reasoning = screen.queryByText("Internal assessment planning");
    if (reasoning) expect(reasoning).not.toBeVisible();
  });

  it("does not hide an existing lesson when later work retrieves more sources", async () => {
    render(<AssistantMessage msg={{ content: lesson + transition, capability: "mastery_path", events: lessonEvents(false, "rag") }} />);
    expect(screen.getByText(lesson)).toBeVisible();
    expect(screen.getByText(transition)).toBeVisible();
    expect(await screen.findByText(question.prompt)).toBeVisible();
  });

  it("keeps ordinary chat commentary folded when no Mastery question is posed", async () => {
    const events = lessonEvents(false, "rag").filter((item) => !(item.type === "tool_result" && item.metadata?.tool_metadata));
    render(<AssistantMessage msg={{ content: lesson + transition, capability: "chat", events }} />);
    expect(screen.queryByText(lesson)).not.toBeVisible();
  });

  it("does not promote the process before an earlier resolved clarification", async () => {
    const planning = "First choose which source to use.";
    const events = [
      event("content", planning, { call_id: "planning-round", call_kind: "agent_loop_round" }),
      event("tool_call", "ask_user", { call_id: "clarification-1", tool_name: "ask_user", assistant_content_offset: planning.length }),
      event("tool_result", "", { tool_call_id: "clarification-1", tool_metadata: { ask_user: { questions: [{ id: "source", prompt: "Which source?" }] } } }),
      event("progress", "", { ask_user_resolved: true, ask_user_tool_call_id: "clarification-1", answers: [{ questionId: "source", text: "Textbook" }], assistant_content_offset: planning.length }),
      ...lessonEvents(false),
    ];
    render(<AssistantMessage msg={{ content: planning + lesson + transition, capability: "mastery_path", events }} />);
    expect(screen.queryByText(planning)).not.toBeVisible();
    expect(screen.getByText(lesson)).toBeVisible();
    expect(await screen.findByText(question.prompt)).toBeVisible();
  });

  it("does not restore a rejected answer as visible teaching", async () => {
    const rejected = "A rejected explanation that must not become lesson text.";
    const events = [
      event("content", rejected, { call_id: "rejected-round", call_kind: "agent_loop_round" }),
      event("progress", "", { trace_kind: "call_status", call_state: "complete", answer_visible: false, call_id: "rejected-round" }),
      ...lessonEvents(false),
    ];
    render(<AssistantMessage msg={{ content: lesson + transition, capability: "mastery_path", events }} />);
    const rejectedText = screen.queryByText(rejected);
    if (rejectedText) expect(rejectedText).not.toBeVisible();
    expect(screen.getByText(lesson)).toBeVisible();
    expect(await screen.findByText(question.prompt)).toBeVisible();
  });
});
