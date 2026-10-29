import { act, render, screen } from "@testing-library/react";
import { useEffect, useRef } from "react";
import { expect, it, vi } from "vitest";
import {
  QuizFollowupProvider,
  useFollowupThread,
  useQuizFollowupController,
  type QuizFollowupController,
} from "@/context/QuizFollowupContext";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/lib/notebook-api", () => ({ updateNotebookEntry: vi.fn() }));

const clients = vi.hoisted(
  () =>
    [] as Array<{
      onEvent: (event: Record<string, unknown>) => void;
      send: ReturnType<typeof vi.fn>;
      disconnect: ReturnType<typeof vi.fn>;
    }>,
);

vi.mock("@/features/chat/transport/UnifiedTurnClient", () => {
  class MockUnifiedTurnClient {
    connected = false;
    send = vi.fn();
    sendAwaitingAck = vi.fn().mockResolvedValue(true);
    disconnect = vi.fn();
    constructor(public onEvent: (event: Record<string, unknown>) => void) {
      clients.push(this);
    }
    connect() {
      this.connected = true;
    }
  }
  return { UnifiedTurnClient: MockUnifiedTurnClient };
});

const KEY = "side-chat:parent-1:abc";

function Probe({ onReady }: { onReady: (controller: QuizFollowupController) => void }) {
  const controller = useQuizFollowupController();
  const thread = useFollowupThread(KEY);
  const ready = useRef(false);
  useEffect(() => {
    if (ready.current) return;
    ready.current = true;
    onReady(controller);
  }, [controller, onReady]);
  return <output>{thread.isStreaming ? "streaming" : "idle"}</output>;
}

it("stops a side thread's turn the way the main chat does", async () => {
  let controller: QuizFollowupController | null = null;
  render(
    <QuizFollowupProvider>
      <Probe onReady={(value) => (controller = value)} />
    </QuizFollowupProvider>,
  );

  await act(async () => {
    controller!.sendMessage({
      questionKey: KEY,
      content: "Why does fork return twice?",
      attachments: [],
      config: {
        selection_tutor_context: { scope: "conversation", parent_session_id: "parent-1" },
      },
    });
  });
  const client = clients[0];
  expect(client.send).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "start_turn",
      selection_tutor_context: { scope: "conversation", parent_session_id: "parent-1" },
    }),
  );
  await act(async () => {
    client.onEvent({
      type: "session",
      metadata: { session_id: "thread-1", turn_id: "turn-1" },
    });
  });
  expect(screen.getByText("streaming")).toBeInTheDocument();

  await act(async () => controller!.cancelTurn(KEY));

  expect(client.send).toHaveBeenLastCalledWith({ type: "cancel_turn", turn_id: "turn-1" });
  expect(client.disconnect).toHaveBeenCalled();
  expect(screen.getByText("idle")).toBeInTheDocument();
});
