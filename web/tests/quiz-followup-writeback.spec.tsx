import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useRef } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  QuizFollowupProvider,
  useFollowupThread,
  useQuizFollowupController,
} from "@/context/QuizFollowupContext";
import { updateNotebookEntry } from "@/lib/notebook-api";
import type { QuizQuestion } from "@/lib/quiz-types";

const clientInstances = vi.hoisted(
  () =>
    [] as Array<{
      onEvent: (event: {
        type: string;
        session_id?: string;
        turn_id?: string | null;
      }) => void;
    }>,
);

vi.mock("@/lib/notebook-api", () => ({
  updateNotebookEntry: vi.fn(),
}));

vi.mock("@/features/chat/transport/UnifiedTurnClient", () => {
  class MockUnifiedTurnClient {
    connected = false;
    onEvent: (event: {
      type: string;
      session_id?: string;
      turn_id?: string | null;
    }) => void;
    send = vi.fn();
    sendAwaitingAck = vi.fn().mockResolvedValue(true);
    disconnect = vi.fn();
    constructor(
      onEvent: (event: {
        type: string;
        session_id?: string;
        turn_id?: string | null;
      }) => void,
    ) {
      this.onEvent = onEvent;
      clientInstances.push(this);
    }
    connect() {
      this.connected = true;
    }
  }
  return { UnifiedTurnClient: MockUnifiedTurnClient };
});

const QUESTION_KEY = "q1";
const ENTRY_ID = 42;
const SESSION_ID = "sess-abc";

const QUESTION = {
  question_id: "q1",
  question: "Which?",
  question_type: "multiple_choice",
  options: { A: "one", B: "two" },
  correct_answer: "B",
  explanation: "",
} as unknown as QuizQuestion;

function Probe({ questionKey }: { questionKey: string }) {
  const controller = useQuizFollowupController();
  const thread = useFollowupThread(questionKey);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    controller.openFollowupTab({
      questionKey,
      question: QUESTION,
      userAnswer: "B",
      isCorrect: true,
      answerImages: [],
      aiJudgment: "",
      parentQuizSessionId: null,
      notebookEntryId: ENTRY_ID,
      followupSessionId: null,
      language: "en",
      tabLabel: "Q1 follow-up",
    });
    controller.sendMessage({
      questionKey,
      content: "why is B correct?",
      attachments: [],
    });
  }, [controller, questionKey]);
  if (thread.error) {
    return <div role="alert">{thread.error}</div>;
  }
  return null;
}

function renderFollowup() {
  return render(
    <QuizFollowupProvider>
      <Probe questionKey={QUESTION_KEY} />
    </QuizFollowupProvider>,
  );
}

function emitSessionEvent() {
  const client = clientInstances.at(-1);
  if (!client) throw new Error("follow-up runner client was not created");
  act(() => {
    client.onEvent({
      type: "session",
      session_id: SESSION_ID,
      turn_id: "turn-1",
    });
  });
}

beforeEach(() => {
  clientInstances.length = 0;
  vi.mocked(updateNotebookEntry).mockReset();
});

it("retries a transient session-id writeback failure and stays silent on success", async () => {
  vi.mocked(updateNotebookEntry)
    .mockRejectedValueOnce(new Error("flaky network"))
    .mockResolvedValue(undefined);
  renderFollowup();
  emitSessionEvent();
  await waitFor(() => expect(updateNotebookEntry).toHaveBeenCalledTimes(2));
  expect(updateNotebookEntry).toHaveBeenNthCalledWith(2, ENTRY_ID, {
    followup_session_id: SESSION_ID,
  });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("surfaces a visible error when the session-id writeback keeps failing", async () => {
  vi.mocked(updateNotebookEntry).mockRejectedValue(new Error("offline"));
  renderFollowup();
  emitSessionEvent();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /notebook entry/i,
  );
  expect(updateNotebookEntry).toHaveBeenCalledTimes(2);
  expect(updateNotebookEntry).toHaveBeenCalledWith(ENTRY_ID, {
    followup_session_id: SESSION_ID,
  });
});

it("writes the session id back exactly once on success", async () => {
  vi.mocked(updateNotebookEntry).mockResolvedValue(undefined);
  renderFollowup();
  emitSessionEvent();
  await waitFor(() => expect(updateNotebookEntry).toHaveBeenCalledTimes(1));
  expect(updateNotebookEntry).toHaveBeenCalledWith(ENTRY_ID, {
    followup_session_id: SESSION_ID,
  });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
