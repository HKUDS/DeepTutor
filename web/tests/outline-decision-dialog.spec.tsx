import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { latestPendingAskUser } from "@/components/chat/home/AskUserOptions";
import { OutlineDecisionDialog } from "@/components/space/learning/OutlineDecisionDialog";
import { ChatMessageList } from "@/features/chat/messages";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { initI18n } from "@/i18n/init";

initI18n("en");

function event(
  type: StreamEvent["type"],
  metadata: Record<string, unknown>,
  content = "",
): StreamEvent {
  return {
    type,
    content,
    metadata,
    source: "mastery_path",
    stage: "responding",
    session_id: "s1",
    turn_id: "t1",
    seq: 0,
    timestamp: 0,
  };
}

const choice = event("tool_result", {
  tool_call_id: "ask-1",
  tool_metadata: {
    ask_user: {
      questions: [
        {
          id: "scope",
          prompt: "Which part of the outline should change?",
          options: [
            { label: "Keep the order", description: "Only reword one point" },
            { label: "Move module 2 first", description: "Same points, new sequence" },
          ],
        },
      ],
    },
  },
});

const resolved = event("progress", {
  ask_user_resolved: true,
  ask_user_tool_call_id: "ask-1",
  answers: [{ questionId: "scope", text: "Move module 2 first" }],
});

function transcript(events: StreamEvent[], deferPendingAskUser: boolean) {
  return (
    <ChatMessageList
      messages={[
        {
          id: 1,
          role: "assistant",
          content: "The draft is ready.",
          capability: "mastery_path",
          parentMessageId: null,
          events,
        },
      ]}
      isStreaming={false}
      onCopyAssistantMessage={vi.fn(async () => undefined)}
      onRegenerateMessage={vi.fn()}
      deferPendingAskUser={deferPendingAskUser}
    />
  );
}

describe("outline decisions", () => {
  it("names the options above the input, then reveals them after confirmation", async () => {
    const submit = vi.fn();
    const card = latestPendingAskUser([{ events: [choice] }]);
    expect(card).not.toBeNull();
    render(<OutlineDecisionDialog data={card!} onSubmit={submit} />);

    expect(screen.getByText("2 options need your choice")).toBeVisible();
    expect(screen.queryByText("Move module 2 first")).toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Review the options" }));
    expect(
      screen.getByText("Which part of the outline should change?"),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: /Move module 2 first/ }));
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(submit).toHaveBeenCalledWith({
      text: "Move module 2 first",
      answers: [{ questionId: "scope", text: "Move module 2 first" }],
    });
  });

  it("keeps the pending choice out of the transcript, then records the selection", () => {
    const { rerender } = render(transcript([choice], true));
    expect(screen.queryByText("Move module 2 first")).toBeNull();
    expect(screen.queryByTestId("outline-decision-pending")).toBeNull();
    expect(screen.getByText("The draft is ready.")).toBeVisible();

    rerender(transcript([choice, resolved], true));
    expect(screen.queryByTestId("outline-decision-pending")).toBeNull();
    expect(screen.getByTestId("ask-user-answers")).toHaveTextContent(
      "Move module 2 first",
    );
    expect(
      screen.getByText("Which part of the outline should change?"),
    ).toBeVisible();
  });

  it("still offers the choice inline outside outline editing", () => {
    render(transcript([choice], false));
    expect(screen.getByRole("button", { name: /Move module 2 first/ })).toBeVisible();
    expect(screen.queryByTestId("outline-decision-pending")).toBeNull();
  });

  it("stops at the newest resolved card", () => {
    expect(
      latestPendingAskUser([
        { events: [choice] },
        { events: [choice, resolved] },
      ]),
    ).toBeNull();
    expect(
      latestPendingAskUser([{ events: [] }, { events: [choice] }])?.payload
        .questions[0]?.prompt,
    ).toBe("Which part of the outline should change?");
  });
});
