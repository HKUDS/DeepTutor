import { useEffect } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import {
  AskUserOptions,
  extractAskUserPayload,
} from "@/components/chat/home/AskUserOptions";
import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { initI18n } from "@/i18n/init";

initI18n("en");

// Keep the real adapter and both transport layers: the bug only appears
// when submitting an answer copies the session cursor back into the socket.
class TestSocket extends EventTarget {
  static instances: TestSocket[] = [];
  readyState = 0;
  sent: Record<string, unknown>[] = [];

  constructor() {
    super();
    TestSocket.instances.push(this);
  }

  open() {
    this.readyState = 1;
    this.dispatchEvent(new Event("open"));
  }

  send(data: string) {
    this.sent.push(JSON.parse(data));
  }

  close() {
    this.readyState = 3;
    this.dispatchEvent(new Event("close"));
  }

  frame(
    turnId: string,
    seq: number,
    type: string,
    metadata = {},
    content = "",
  ) {
    this.dispatchEvent(
      new MessageEvent("message", {
        data: JSON.stringify({
          protocol_version: "2.0",
          type,
          turn_id: turnId,
          session_id: "session-quiz",
          seq,
          timestamp: Date.now() / 1000,
          metadata,
          content,
        }),
      }),
    );
  }
}

function Harness() {
  const chat = useChatStateAdapter();
  useEffect(() => {
    chat.newSession();
    // Initialize only once; subsequent renders belong to the adapter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const last = chat.state.messages.at(-1);
  const card = extractAskUserPayload(last?.events);
  return (
    <>
      <button onClick={() => chat.sendMessage("Quiz me")}>Start turn</button>
      <span data-testid="streaming">{String(chat.state.isStreaming)}</span>
      <span data-testid="answer">{last?.content}</span>
      {card && <AskUserOptions key={card.payload.questions[0]?.prompt} data={card} onSubmit={chat.submitUserReply} />}
    </>
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  TestSocket.instances = [];
});

async function poseCard() {
  vi.stubGlobal("WebSocket", TestSocket);
  const user = userEvent.setup();
  render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
  await user.click(screen.getByRole("button", { name: "Start turn" }));
  const socket = TestSocket.instances.at(-1)!;
  act(() => socket.open());
  await waitFor(() => expect(socket.sent.some((m) => m.type === "start_turn")).toBe(true));
  act(() => {
    socket.frame("turn-quiz", 1, "session");
    socket.frame("turn-quiz", 2, "tool_result", {
      tool_call_id: "call-quiz",
      tool_metadata: { ask_user: { questions: [
        { id: "q1", prompt: "Which update?", options: [{ label: "Overwrite" }] },
      ] } },
    });
  });
  await user.click(screen.getByRole("button", { name: /Overwrite/ }));
  vi.useFakeTimers();
  return socket;
}

function acknowledge(socket: TestSocket, commandId: unknown, accepted = true) {
  act(() => socket.dispatchEvent(new MessageEvent("message", {
    data: JSON.stringify({
      protocol_version: "2.0", type: "command_ack", command_type: "submit_user_reply",
      command_id: commandId, accepted, turn_id: "turn-quiz",
    }),
  })));
}

it("keeps a reply queued through a long reconnect without ending the turn (#1648)", async () => {
  const socket = await poseCard();
  act(() => socket.close());
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  await act(async () => { await vi.advanceTimersByTimeAsync(12_500); });
  expect(screen.getByText("Sending your answers…")).toBeVisible();
  expect(screen.getByTestId("streaming")).toHaveTextContent("true");
  const resumed = TestSocket.instances.at(-1)!;
  act(() => resumed.open());
  const reply = resumed.sent.find((m) => m.type === "submit_user_reply")!;
  expect(reply).toMatchObject({ turn_id: "turn-quiz", text: "Overwrite" });
  acknowledge(resumed, reply.command_id);
  await act(async () => { await vi.advanceTimersByTimeAsync(35_000); });
  expect(screen.queryByText(/Check your connection and retry/)).not.toBeInTheDocument();
});

it("allows an unconfirmed reply to retry with the same command id (#1648)", async () => {
  const socket = await poseCard();
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  const reply = socket.sent.find((m) => m.type === "submit_user_reply")!;
  await act(async () => { await vi.advanceTimersByTimeAsync(30_001); });
  expect(screen.getByText("Couldn't confirm your answer. Check your connection and retry.")).toBeVisible();
  expect(screen.queryByText(/This question is no longer active/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Overwrite/ })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  const replies = socket.sent.filter((m) => m.type === "submit_user_reply");
  expect(replies).toHaveLength(2);
  expect(replies[1].command_id).toBe(reply.command_id);
  acknowledge(socket, reply.command_id, false);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByText(/This question is no longer active/)).toBeVisible();
});

it("uses a new command id for a later question with identical answers", async () => {
  const socket = await poseCard();
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  const first = socket.sent.find((m) => m.type === "submit_user_reply")!;
  acknowledge(socket, first.command_id);
  act(() => {
    socket.frame("turn-quiz", 3, "progress", {
      ask_user_resolved: true, ask_user_tool_call_id: "call-quiz",
      answers: [{ questionId: "q1", text: "Overwrite" }],
    });
    socket.frame("turn-quiz", 4, "tool_result", {
      tool_call_id: "call-quiz-2",
      tool_metadata: { ask_user: { questions: [
        { id: "q1", prompt: "Which update next?", options: [{ label: "Overwrite" }] },
      ] } },
    });
  });
  // The card may preserve the choice between identical question shapes.
  const option = screen.getByRole("button", { name: /Overwrite/ });
  if (option.getAttribute("aria-pressed") !== "true") fireEvent.click(option);
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  const replies = socket.sent.filter((m) => m.type === "submit_user_reply");
  expect(replies).toHaveLength(2);
  expect(replies[1].command_id).not.toBe(first.command_id);
  acknowledge(socket, replies[1].command_id);
});

it("resumes an ask_user in a shorter second turn without skipping its reply or done", async () => {
  vi.stubGlobal("WebSocket", TestSocket);
  const user = userEvent.setup();
  render(
    <ChatStateAdapterProvider>
      <Harness />
    </ChatStateAdapterProvider>,
  );

  await user.click(screen.getByRole("button", { name: "Start turn" }));
  const first = TestSocket.instances.at(-1)!;
  act(() => first.open());
  await waitFor(() =>
    expect(first.sent.some((m) => m.type === "start_turn")).toBe(true),
  );
  act(() => {
    first.frame("turn-long", 1, "session");
    for (let seq = 2; seq <= 8; seq++) {
      first.frame("turn-long", seq, "content", {}, "Earlier text. ");
    }
    first.frame("turn-long", 9, "done", {
      status: "completed",
      user_message_id: 1,
      assistant_message_id: 2,
    });
  });
  expect(screen.getByTestId("streaming")).toHaveTextContent("false");

  await user.click(screen.getByRole("button", { name: "Start turn" }));
  const second = TestSocket.instances.at(-1)!;
  act(() => second.open());
  await waitFor(() =>
    expect(second.sent.some((m) => m.type === "start_turn")).toBe(true),
  );
  act(() => {
    second.frame("turn-quiz", 1, "session");
    second.frame("turn-quiz", 2, "tool_result", {
      tool_call_id: "call-quiz",
      tool_metadata: {
        ask_user: {
          questions: [
            {
              id: "q1",
              prompt: "Which update?",
              options: [{ label: "Overwrite" }],
            },
          ],
        },
      },
    });
  });
  await user.click(screen.getByRole("button", { name: /Overwrite/ }));
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(second.sent.at(-1)).toMatchObject({
    type: "submit_user_reply",
    turn_id: "turn-quiz",
    text: "Overwrite",
  });
  expect(screen.getByText("Sending your answers…")).toBeVisible();

  act(() =>
    second.frame("turn-quiz", 3, "progress", {
      ask_user_resolved: true,
      ask_user_tool_call_id: "call-quiz",
      answers: [{ questionId: "q1", text: "Overwrite" }],
    }),
  );
  expect(screen.queryByText("Sending your answers…")).not.toBeInTheDocument();
  expect(screen.getByTestId("ask-user-answers")).toHaveTextContent("Overwrite");

  act(() => {
    second.frame(
      "turn-quiz",
      4,
      "content",
      {},
      "Correct, the field is overwritten.",
    );
    second.frame("turn-quiz", 5, "done", {
      status: "completed",
      user_message_id: 3,
      assistant_message_id: 4,
    });
  });
  expect(screen.getByTestId("answer")).toHaveTextContent(
    "Correct, the field is overwritten.",
  );
  expect(screen.getByTestId("streaming")).toHaveTextContent("false");
});
