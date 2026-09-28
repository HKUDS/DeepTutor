import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WatchingProvider } from "@/context/WatchingContext";
import { ChatMessageList } from "@/features/chat/messages";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { compactTracePreview } from "@/features/chat/trace/memory";
import { initI18n } from "@/i18n/init";

initI18n("en");

const intro = "Let me clarify your learning goal.\n\n";
const followup = "I will check your current topics.\n\n";
const answer = "You are studying state machines.";

function event(
  type: StreamEvent["type"],
  metadata: Record<string, unknown>,
  content = "",
): StreamEvent {
  return {
    type,
    metadata,
    content,
    source: "chat",
    stage: "responding",
    session_id: "s1",
    turn_id: "t1",
    seq: 0,
    timestamp: 0,
  };
}

/**
 * The call itself, shaped the way the dispatcher shapes it: a
 * ``call_kind="tool_planning"`` / ``trace_group="tool_call"`` row naming the
 * tool, which is what turns it into an activity row rather than a bare stage
 * label.
 */
function asking(id: string, offset: number) {
  return event(
    "tool_call",
    {
      call_id: `trace-${id}`,
      trace_id: `trace-${id}`,
      label: "Tool call",
      call_kind: "tool_planning",
      trace_role: "tool",
      trace_group: "tool_call",
      tool_call_id: id,
      tool_name: "ask_user",
      assistant_content_offset: offset,
      args: { questions: [{ prompt: `Which goal (${id})?` }] },
    },
    "ask_user",
  );
}

function question(id: string, offset: number) {
  return event("tool_result", {
    tool_call_id: id,
    assistant_content_offset: offset,
    tool_metadata: {
      ask_user: {
        questions: [
          {
            id,
            prompt: `Which goal (${id})?`,
            options: [{ label: "Continue learning" }],
          },
        ],
      },
    },
  });
}

function resolved(id: string) {
  return event("progress", {
    ask_user_resolved: true,
    ask_user_tool_call_id: id,
    answers: [{ questionId: id, text: "Continue learning" }],
  });
}

const pending = [
  event("content", { call_id: "r1", call_kind: "agent_loop_round" }, intro),
  asking("q1", intro.length),
  question("q1", intro.length),
];
const resumed = [
  ...pending,
  resolved("q1"),
  event("content", { call_id: "r2", call_kind: "agent_loop_round" }, followup),
  event(
    "tool_call",
    {
      call_id: "topics",
      label: "Current topics",
      assistant_content_offset: intro.length + followup.length,
    },
    "mastery_topics",
  ),
  event(
    "tool_result",
    {
      call_id: "topics",
      assistant_content_offset: intro.length + followup.length,
    },
    "State machines",
  ),
];

function conversation(
  events: StreamEvent[],
  content: string,
  isStreaming: boolean,
  onSubmitUserReply = vi.fn(),
) {
  return (
    <WatchingProvider>
      <ChatMessageList
        messages={[
          { id: 1, role: "assistant", parentMessageId: null, content, events },
        ]}
        isStreaming={isStreaming}
        onSubmitUserReply={onSubmitUserReply}
        onCopyAssistantMessage={async () => undefined}
        onRegenerateMessage={() => undefined}
      />
    </WatchingProvider>
  );
}

describe("ask_user trace continuity", () => {
  it("joins the answered card and resumed work under the original disclosure through completion and reload", async () => {
    const user = userEvent.setup();
    const submit = vi.fn(async () => true);
    const { container, rerender } = render(
      conversation(pending, intro, true, submit),
    );
    const trace = screen.getByText(intro.trim()).closest(".grid")!;
    const toggle = trace.parentElement!.querySelector("button")!;

    // An explicitly collapsed trace must never hide the pending question.
    await user.click(toggle);
    expect(
      screen.getByText(`Which goal (q1)?`).closest(".opacity-0"),
    ).toBeNull();
    await user.click(screen.getByRole("button", { name: /Continue learning/ }));
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        answers: [{ questionId: "q1", text: "Continue learning" }],
      }),
    );

    rerender(conversation(resumed, intro + followup, true, submit));
    expect(screen.getByTestId("ask-user-answers").closest(".grid")).toBe(trace);
    expect(screen.getByText(followup.trim()).closest(".grid")).toBe(trace);
    expect(screen.getByText("Current topics").closest(".grid")).toBe(trace);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByText(followup.trim()).closest(".opacity-0")).toBeNull();
    // Chat does not fold an answered exchange away, so the answer is on
    // screen without being asked for.
    expect(screen.getByText("Continue learning")).toBeVisible();

    const completed = [
      ...resumed,
      event(
        "content",
        { call_id: "r3", call_kind: "agent_loop_round" },
        answer,
      ),
      event("done", { status: "completed" }),
    ];
    for (const events of [completed, compactTracePreview(completed).events]) {
      rerender(conversation(events, intro + followup + answer, false, submit));
      expect(screen.getByText(followup.trim()).closest(".grid")).toBe(trace);
      expect(screen.getByTestId("ask-user-answers").closest(".grid")).toBe(
        trace,
      );
      // Including after compaction: the asking is semantic, so a reloaded
      // turn still shows the step that produced the answers.
      expect(screen.getByText("Asking you").closest(".grid")).toBe(trace);
      expect(screen.getByText(answer).closest(".grid")).toBeNull();
      expect(
        container.querySelectorAll('div.grid[class*="grid-template-rows"]'),
      ).toHaveLength(1);
    }
  });

  it("keeps the asking itself in the trace, above the card it opened", () => {
    const { container } = render(conversation(pending, intro, true));
    const trace = screen.getByText(intro.trim()).closest(".grid")!;
    const row = screen.getByText("Asking you");

    // Stopping to ask is a step the agent took. Suppressing every event that
    // shared the card's call id took this row down with the payload, leaving a
    // trace in which the answers appear out of nowhere.
    expect(row.closest(".grid")).toBe(trace);
    const card = screen.getByText("Which goal (q1)?");
    expect(
      row.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // The row names the step; the card says what was asked. The question is
    // not restated inside the trace.
    expect(screen.getAllByText("Which goal (q1)?")).toHaveLength(1);
    expect(
      container.querySelectorAll('div.grid[class*="grid-template-rows"]'),
    ).toHaveLength(1);
  });

  it("keeps repeated clarifications in order, with only the pending question outside the trace", () => {
    const events = [
      ...resumed,
      asking("q2", intro.length + followup.length),
      question("q2", intro.length + followup.length),
    ];
    const { rerender } = render(conversation(events, intro + followup, true));
    const trace = screen.getByText(intro.trim()).closest(".grid")!;
    expect(screen.getByTestId("ask-user-answers").closest(".grid")).toBe(trace);
    expect(screen.getByText("Which goal (q2)?").closest(".grid")).toBeNull();

    rerender(conversation([...events, resolved("q2")], intro + followup, true));
    const cards = screen.getAllByTestId("ask-user-answers");
    expect(cards).toHaveLength(2);
    for (const card of cards) expect(card.closest(".grid")).toBe(trace);
    const prose = screen.getByText(followup.trim());
    expect(
      cards[0].compareDocumentPosition(prose) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      prose.compareDocumentPosition(cards[1]) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("creates one trace when the turn starts with a question", () => {
    render(
      conversation(
        [
          asking("q1", 0),
          question("q1", 0),
          resolved("q1"),
          event(
            "content",
            { call_id: "r2", call_kind: "agent_loop_round" },
            followup,
          ),
          event(
            "tool_call",
            {
              call_id: "topics",
              label: "Current topics",
              assistant_content_offset: followup.length,
            },
            "mastery_topics",
          ),
        ],
        followup,
        true,
      ),
    );
    const trace = screen.getByTestId("ask-user-answers").closest(".grid");
    expect(trace).not.toBeNull();
    expect(screen.getByText(followup.trim()).closest(".grid")).toBe(trace);
    expect(screen.getByText("Current topics").closest(".grid")).toBe(trace);
  });
});
