import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

/**
 * The composer under test only ever calls back into these two functions, so
 * the interesting behaviour is which one gets the text — and, when the reply
 * is refused, whether the text survives at all.
 */
const chat = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  submitUserReply: vi.fn(async () => true),
  state: {
    messages: [
      {
        id: 1,
        role: "assistant" as const,
        content: "",
        parentMessageId: null,
        events: [
          {
            type: "tool_result",
            metadata: {
              tool_call_id: "call-1",
              tool_metadata: {
                ask_user: { questions: [{ id: "q", prompt: "Which one?" }] },
              },
            },
          },
        ],
      },
    ],
    knowledgeBases: [],
    llmSelection: null,
    personaSelection: null,
    isStreaming: false,
  },
}));

vi.mock("@/features/chat/ChatStateAdapter", () => ({
  useChatStateAdapter: () => ({
    state: chat.state,
    sendMessage: chat.sendMessage,
    submitUserReply: chat.submitUserReply,
    cancelStreamingTurn: () => undefined,
    setKBs: () => undefined,
    setLLMSelection: () => undefined,
    setPersonaSelection: () => undefined,
  }),
}));

vi.mock("@/hooks/useWorkspaceChatActions", () => ({
  useWorkspaceChatActions: () => ({
    capabilities: [],
    activeCapabilityValue: "",
    selectCapability: () => undefined,
  }),
}));

vi.mock("@/hooks/useContextBudget", () => ({
  useContextBudget: () => null,
}));

/** Stands in for the real composer: one button that submits fixed text. */
vi.mock("@/components/chat/home/StandaloneComposer", () => ({
  default: ({
    onSubmit,
  }: {
    onSubmit: (submission: Record<string, unknown>) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onSubmit({
          content: "C",
          attachments: [],
          notebookReferences: [],
          historyReferences: [],
          bookReferences: [],
          questionNotebookReferences: [],
          memoryReferences: [],
          config: undefined,
          subagentBudget: undefined,
          persona: null,
        })
      }
    >
      send
    </button>
  ),
}));

const { MasteryComposer } = await import(
  "@/components/space/learning/MasteryComposer"
);

describe("composer routing while a question is open", () => {
  beforeEach(() => {
    chat.sendMessage.mockClear();
    chat.submitUserReply.mockClear();
    chat.submitUserReply.mockImplementation(async () => true);
  });

  it("routes the text to the open question when the turn accepts it", async () => {
    const user = userEvent.setup();
    render(<MasteryComposer placeholder="Ask" />);
    await user.click(screen.getByRole("button", { name: "send" }));
    await waitFor(() =>
      expect(chat.submitUserReply).toHaveBeenCalledWith({ text: "C" }),
    );
    expect(chat.sendMessage).not.toHaveBeenCalled();
  });

  /**
   * The #1273 shape. The backend refuses the reply because the turn that
   * asked is gone; the composer has already cleared the box. Returning here
   * discarded what the learner typed — while the error told them to send a
   * new message, which is the very thing this branch was intercepting.
   */
  it("re-sends as a new message when the reply is refused", async () => {
    chat.submitUserReply.mockImplementation(async () => false);
    const user = userEvent.setup();
    render(<MasteryComposer placeholder="Ask" />);
    await user.click(screen.getByRole("button", { name: "send" }));
    await waitFor(() => expect(chat.sendMessage).toHaveBeenCalled());
    expect(chat.sendMessage.mock.calls[0][0]).toBe("C");
  });
});
