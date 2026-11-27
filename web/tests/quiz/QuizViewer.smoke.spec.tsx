import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";
import QuizViewer from "@/components/quiz/QuizViewer";
import type { QuizQuestion } from "@/lib/quiz-types";
import type { QuizJudgeHandlers } from "@/lib/quiz-judge";

initI18n("en");

const mocks = vi.hoisted(() => ({
  lookupNotebookEntry: vi.fn(),
  updateNotebookEntry: vi.fn(),
  upsertNotebookEntry: vi.fn(),
  listCategories: vi.fn(),
  addEntryToCategory: vi.fn(),
  createCategory: vi.fn(),
  recordQuizResults: vi.fn(),
  startQuizJudge: vi.fn(),
  readFileAsBase64: vi.fn(),
  openFollowupTab: vi.fn(),
  judgeHandle: { close: vi.fn(), cancel: vi.fn() },
  judgeHandlers: null as QuizJudgeHandlers | null,
}));

vi.mock("@/lib/notebook-api", () => ({
  lookupNotebookEntry: mocks.lookupNotebookEntry,
  updateNotebookEntry: mocks.updateNotebookEntry,
  upsertNotebookEntry: mocks.upsertNotebookEntry,
  listCategories: mocks.listCategories,
  addEntryToCategory: mocks.addEntryToCategory,
  createCategory: mocks.createCategory,
}));

vi.mock("@/lib/session-api", () => ({
  recordQuizResults: mocks.recordQuizResults,
}));

vi.mock("@/lib/quiz-judge", () => ({
  startQuizJudge: mocks.startQuizJudge,
  readFileAsBase64: mocks.readFileAsBase64,
}));

vi.mock("@/context/QuizFollowupContext", () => ({
  useQuizFollowupController: () => ({
    openFollowupTab: mocks.openFollowupTab,
  }),
  useAllFollowupThreads: () => ({}),
}));

// Keep the passthrough text so assertions can target question/option/
// judgment strings without pulling react-markdown + KaTeX into jsdom.
vi.mock("@/components/common/MarkdownRenderer", () => ({
  default: ({ content }: { content: string }) => <>{content}</>,
}));

const choiceQuestion: QuizQuestion = {
  question_id: "q_1",
  question: "What is the capital of France?",
  question_type: "choice",
  options: { A: "Berlin", B: "Paris", C: "Madrid" },
  correct_answer: "B",
  explanation: "Paris is the capital of France.",
  difficulty: "easy",
};

const conceptQuestion: QuizQuestion = {
  question_id: "q_2",
  question: "The Earth is perfectly flat.",
  question_type: "concept",
  correct_answer: "false",
  explanation: "The Earth is an oblate spheroid.",
  difficulty: "easy",
};

const shortAnswerQuestion: QuizQuestion = {
  question_id: "q_3",
  question: "Explain photosynthesis briefly.",
  question_type: "short_answer",
  correct_answer: "Plants convert light into chemical energy.",
  explanation: "Chloroplasts capture light energy.",
  difficulty: "medium",
};

function renderViewer(questions: QuizQuestion[], props: {
  sessionId?: string | null;
  turnId?: string | null;
} = {}) {
  return render(
    <StrictMode>
      <QuizViewer
        questions={questions}
        sessionId={props.sessionId ?? null}
        turnId={props.turnId ?? null}
        language="en"
      />
    </StrictMode>,
  );
}

beforeEach(() => {
  mocks.lookupNotebookEntry.mockResolvedValue(null);
  mocks.updateNotebookEntry.mockResolvedValue({});
  mocks.upsertNotebookEntry.mockResolvedValue({
    id: 11,
    bookmarked: false,
    user_answer_images: [],
  });
  mocks.listCategories.mockResolvedValue([]);
  mocks.addEntryToCategory.mockResolvedValue(undefined);
  mocks.createCategory.mockResolvedValue({
    id: 1,
    name: "new",
    created_at: 0,
    entry_count: 0,
  });
  mocks.recordQuizResults.mockResolvedValue(undefined);
  mocks.startQuizJudge.mockImplementation(
    (_payload: unknown, handlers: QuizJudgeHandlers) => {
      mocks.judgeHandlers = handlers;
      return mocks.judgeHandle;
    },
  );
});

describe("QuizViewer smoke", () => {
  it("renders nothing for an empty question list", () => {
    const { container } = renderViewer([]);
    expect(container.firstChild).toBeNull();
  });

  it("renders the quiz card with question, options and progress (render smoke)", () => {
    renderViewer([choiceQuestion, conceptQuestion]);
    expect(screen.getByText("What is the capital of France?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Berlin/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Paris/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Madrid/ })).toBeInTheDocument();
    expect(screen.getByText("0/2")).toBeInTheDocument();
    // First question: no previous page, and nothing selected yet.
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Check Answer/ })).toBeDisabled();
  });

  it("grades a correct choice answer and shows the explanation (answer → submit → feedback)", async () => {
    const user = userEvent.setup();
    renderViewer([choiceQuestion]);
    await user.click(screen.getByRole("button", { name: /Paris/ }));
    const submit = screen.getByRole("button", { name: /Check Answer/ });
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(screen.getByText("Correct")).toBeInTheDocument();
    expect(screen.getByText("Explanation")).toBeInTheDocument();
    expect(screen.getByText("Paris is the capital of France.")).toBeInTheDocument();
    // Options lock after submission; the action row flips to retry/judge.
    expect(screen.getByRole("button", { name: /Paris/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /AI Judge/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Check Answer/ })).toBeNull();
  });

  it("marks a wrong choice selection as incorrect and highlights both options", async () => {
    const user = userEvent.setup();
    renderViewer([choiceQuestion]);
    await user.click(screen.getByRole("button", { name: /Berlin/ }));
    await user.click(screen.getByRole("button", { name: /Check Answer/ }));

    expect(screen.getByText("Incorrect")).toBeInTheDocument();
    // Correct option turns green, the wrong pick turns red.
    expect(screen.getByRole("button", { name: /Paris/ }).className).toContain(
      "border-green-500",
    );
    expect(screen.getByRole("button", { name: /Berlin/ }).className).toContain(
      "border-red-400",
    );
  });

  it("retry (redo) path clears selection and feedback, then regrades a new answer", async () => {
    const user = userEvent.setup();
    renderViewer([choiceQuestion]);
    await user.click(screen.getByRole("button", { name: /Paris/ }));
    await user.click(screen.getByRole("button", { name: /Check Answer/ }));
    expect(screen.getByText("Correct")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Retry/ }));
    expect(screen.queryByText("Correct")).toBeNull();
    expect(screen.queryByText("Explanation")).toBeNull();
    // Options are interactive again and no selection is carried over.
    const paris = screen.getByRole("button", { name: /Paris/ });
    expect(paris).toBeEnabled();
    expect(paris.className).not.toContain("border-green-500");
    expect(screen.getByRole("button", { name: /Check Answer/ })).toBeDisabled();

    // Redo with a wrong answer and get regraded accordingly.
    await user.click(screen.getByRole("button", { name: /Berlin/ }));
    await user.click(screen.getByRole("button", { name: /Check Answer/ }));
    expect(screen.getByText("Incorrect")).toBeInTheDocument();
  });

  it("grades concept (true/false) questions via the canonical answer", async () => {
    const user = userEvent.setup();
    renderViewer([conceptQuestion]);
    await user.click(screen.getByRole("button", { name: "False" }));
    await user.click(screen.getByRole("button", { name: /Check Answer/ }));
    expect(screen.getByText("Correct")).toBeInTheDocument();
  });

  it("tracks progress and colors completed chips while navigating", async () => {
    const user = userEvent.setup();
    renderViewer([choiceQuestion, conceptQuestion]);

    await user.click(screen.getByRole("button", { name: /Paris/ }));
    await user.click(screen.getByRole("button", { name: /Check Answer/ }));
    expect(screen.getByText("1/2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("The Earth is perfectly flat.")).toBeInTheDocument();
    // Chip 1 is no longer current and was graded correct → green tint.
    expect(screen.getByRole("button", { name: "1" }).className).toContain(
      "bg-green-100",
    );
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();

    // Chips are also a navigation surface.
    await user.click(screen.getByRole("button", { name: "1" }));
    expect(screen.getByText("What is the capital of France?")).toBeInTheDocument();
  });

  it("persists each submit and records results once every question is answered (mock API)", async () => {
    const user = userEvent.setup();
    renderViewer([choiceQuestion, conceptQuestion], {
      sessionId: "session-1",
      turnId: "turn-1",
    });

    // Turn-scoped notebook lookups hydrate prior answers (#487/#677).
    await waitFor(() => {
      expect(mocks.lookupNotebookEntry).toHaveBeenCalledWith(
        "session-1",
        "q_1",
        "turn-1",
      );
    });

    await user.click(screen.getByRole("button", { name: /Paris/ }));
    await user.click(screen.getByRole("button", { name: /Check Answer/ }));
    await waitFor(() => {
      expect(mocks.upsertNotebookEntry).toHaveBeenCalledWith(
        expect.objectContaining({
          session_id: "session-1",
          turn_id: "turn-1",
          question_id: "q_1",
          user_answer: "B",
          is_correct: true,
        }),
      );
    });

    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "False" }));
    await user.click(screen.getByRole("button", { name: /Check Answer/ }));

    await waitFor(() => {
      expect(mocks.recordQuizResults).toHaveBeenCalledTimes(1);
    });
    const [sessionId, results, turnId] = mocks.recordQuizResults.mock.calls[0];
    expect(sessionId).toBe("session-1");
    expect(turnId).toBe("turn-1");
    expect(results).toEqual([
      expect.objectContaining({
        question_id: "q_1",
        question_type: "choice",
        user_answer: "B",
        correct_answer: "B",
        is_correct: true,
      }),
      expect.objectContaining({
        question_id: "q_2",
        question_type: "concept",
        user_answer: "false",
        is_correct: true,
      }),
    ]);
  });

  it("stays local-only without a turn id: no notebook or result-report calls", async () => {
    const user = userEvent.setup();
    renderViewer([choiceQuestion], { sessionId: "session-1" });

    await user.click(screen.getByRole("button", { name: /Paris/ }));
    await user.click(screen.getByRole("button", { name: /Check Answer/ }));

    // Let microtasks settle; none of the API writes may fire.
    await waitFor(() => {
      expect(screen.getByText("Correct")).toBeInTheDocument();
    });
    expect(mocks.lookupNotebookEntry).not.toHaveBeenCalled();
    expect(mocks.upsertNotebookEntry).not.toHaveBeenCalled();
    expect(mocks.recordQuizResults).not.toHaveBeenCalled();
  });

  it("streams AI judge feedback into the judgment view (mock API)", async () => {
    const user = userEvent.setup();
    renderViewer([shortAnswerQuestion]);

    const textarea = screen.getByPlaceholderText("Type your answer...");
    await user.type(textarea, "Light becomes sugar.");
    await user.click(screen.getByRole("button", { name: /Check Answer/ }));

    // Free-text question graded against the reference first (label +
    // tab can both render; at least the reference block must show).
    expect(
      screen.getAllByText("Reference Answer").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByText("Plants convert light into chemical energy."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /AI Judge/ }));
    expect(mocks.startQuizJudge).toHaveBeenCalledTimes(1);
    const [payload] = mocks.startQuizJudge.mock.calls[0];
    expect(payload).toEqual(
      expect.objectContaining({
        question: "Explain photosynthesis briefly.",
        question_type: "short_answer",
        user_answer: "Light becomes sugar.",
        language: "en",
      }),
    );

    await waitFor(() => {
      expect(screen.getByText("Judging...")).toBeInTheDocument();
    });
    act(() => {
      mocks.judgeHandlers!.onDone("Plants use light to build glucose.");
    });
    await waitFor(() => {
      expect(
        screen.getByText("Plants use light to build glucose."),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("Judging...")).toBeNull();
    // The review block flipped to the judgment tab: the reference
    // section content is hidden (only its tab button remains).
    expect(
      screen.queryByText("Plants convert light into chemical energy."),
    ).toBeNull();
  });

  it("closes in-flight judge handles on unmount", async () => {
    const user = userEvent.setup();
    const { unmount } = renderViewer([shortAnswerQuestion]);

    await user.type(screen.getByPlaceholderText("Type your answer..."), "hi");
    await user.click(screen.getByRole("button", { name: /Check Answer/ }));
    await user.click(screen.getByRole("button", { name: /AI Judge/ }));
    expect(mocks.startQuizJudge).toHaveBeenCalledTimes(1);

    unmount();
    expect(mocks.judgeHandle.close).toHaveBeenCalled();
  });
});
