import { useEffect } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { initI18n } from "@/i18n/init";

initI18n("en");

const transport = vi.hoisted(() => {
  type MockEvent = Record<string, unknown>;
  type EventListener = (event: MockEvent) => void;
  const instances: MockUnifiedTurnClient[] = [];

  class MockUnifiedTurnClient {
    connected = false;
    submitted: Array<Record<string, unknown>> = [];

    constructor(
      private readonly onEvent: EventListener,
      private readonly onClose?: () => void,
    ) {
      instances.push(this);
    }

    connect(): void {
      this.connected = true;
    }

    setResumeState(): void {}

    disconnect(): void {
      this.connected = false;
      this.onClose?.();
    }

    send(message: Record<string, unknown>): void {
      if (message.type !== "start_turn") return;
      window.setTimeout(() => {
        this.onEvent({
          type: "tool_result",
          source: "chat",
          stage: "responding",
          content: "",
          metadata: {
            tool_call_id: "call-1273",
            tool_metadata: {
              ask_user: {
                questions: [{ id: "source", prompt: "Which source?" }],
              },
            },
          },
          turn_id: "turn-1273",
          seq: 1,
          timestamp: Date.now() / 1000,
        });
      }, 0);
      window.setTimeout(() => {
        this.onEvent({
          type: "done",
          source: "chat",
          stage: "responding",
          content: "",
          metadata: { status: "completed" },
          turn_id: "turn-1273",
          seq: 2,
          timestamp: Date.now() / 1000,
        });
      }, 0);
    }

    sendAwaitingAck(message: Record<string, unknown>): Promise<boolean> {
      this.submitted.push(message);
      return Promise.resolve(true);
    }
  }

  return { MockUnifiedTurnClient, instances };
});

vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: transport.MockUnifiedTurnClient,
}));

function Harness() {
  const chat = useChatStateAdapter();

  useEffect(() => {
    chat.newSession();
    // Only initialize the draft once; the provider owns subsequent state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <span data-testid="streaming">{String(chat.state.isStreaming)}</span>
      <button type="button" onClick={() => chat.sendMessage("hello")}>
        Start turn
      </button>
      <button
        type="button"
        onClick={() => {
          void chat.submitUserReply({
            text: "Knowledge center",
            answers: [{ questionId: "source", text: "Knowledge center" }],
          });
        }}
      >
        Submit answer
      </button>
    </div>
  );
}

describe("ask_user terminal turn state", () => {
  it("keeps the pending card addressable after a completed turn", async () => {
    const user = userEvent.setup();
    render(
      <ChatStateAdapterProvider>
        <Harness />
      </ChatStateAdapterProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Start turn" }));
    await waitFor(() =>
      expect(screen.getByTestId("streaming")).toHaveTextContent("false"),
    );

    await user.click(screen.getByRole("button", { name: "Submit answer" }));
    await waitFor(() => {
      const client = transport.instances.at(-1);
      expect(client?.submitted.at(-1)).toMatchObject({
        type: "submit_user_reply",
        turn_id: "turn-1273",
        text: "Knowledge center",
      });
    });
  });
});
