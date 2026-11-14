import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ExtensionResult, type QuizHelpContext } from "@/components/reading/ReadingExtensionBar";
import { ReadingActionCards } from "@/components/reading/workspace/ReadingActionCards";
import { ReadingActionsProvider } from "@/components/reading/ReadingActionsProvider";
import { ReadingActionsContext, useReadingActions } from "@/components/reading/reading-actions-context";
import { initI18n } from "@/i18n/init";
import { listReadingExtensions, runReadingExtension, submitReadingQuizAnswers, type ReadingExtensionResult } from "@/lib/reading-api";

vi.mock("@/lib/auth", () => ({ fetchAuthStatus: vi.fn().mockResolvedValue({}) }));
vi.mock("@/lib/reading-api", () => ({
  listReadingExtensions: vi.fn(), runReadingExtension: vi.fn(), submitReadingQuizAnswers: vi.fn(),
}));
initI18n("en");
const context: QuizHelpContext = {
  locator: 4, selection: "verified phrase",
  actions: [{
    extension: { id: "guided_learning", name: "Guidance", version: "1", protocol_version: "1", actions: [], result_types: ["card"] },
    action: { id: "guide", label: "Guide me", trigger: "toolbar", requires: ["selection"] },
  }],
};
const quiz: ReadingExtensionResult = {
  type: "quiz", title: "", message: "", payload: {
    questions: ["one", "two"].map((id) => ({ id, prompt: `Question ${id}`, choices: ["A", "B"], correct_choice_index: 1 })),
  },
};
const help: ReadingExtensionResult = {
  type: "card", title: "", message: "", payload: { steps: ["Look at the evidence."] },
  quiz_help: { question_id: "one", hints_used: 1 },
};
const onError = vi.fn();
function panel(helpContext = context, result = quiz) {
  return <ExtensionResult result={result} materialId="material" locator={4} closeLabel="Close"
    onClose={vi.fn()} onError={onError} helpContext={helpContext} />;
}
beforeEach(() => { vi.clearAllMocks(); });

it("keeps help inside its question and waits for recorded help before allowing an answer", async () => {
  let finish!: (value: ReadingExtensionResult) => void;
  vi.mocked(runReadingExtension).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  render(panel());
  const first = within(screen.getByRole("group", { name: "Question one" }));
  fireEvent.click(first.getByRole("button", { name: "Guide me" }));
  expect(first.getByRole("button", { name: "A. A" })).toBeDisabled();
  expect(runReadingExtension).toHaveBeenCalledWith("material", "guided_learning", "guide", {
    locator: 4, selection: "verified phrase", locale: "en", question_id: "one", help_request_id: expect.any(String),
  });
  await act(async () => { finish(help); });
  expect(first.getByText("Look at the evidence.")).toBeInTheDocument();
  expect(first.getByText("Recorded help: 1")).toBeInTheDocument();
  expect(first.getByRole("button", { name: "A. A" })).not.toBeDisabled();
  expect(within(screen.getByRole("group", { name: "Question two" })).queryByText("Recorded help: 1")).not.toBeInTheDocument();
});

it("reuses the request id after a failed response without claiming success", async () => {
  vi.mocked(runReadingExtension).mockRejectedValueOnce(new Error("Temporary failure"));
  render(panel());
  const first = within(screen.getByRole("group", { name: "Question one" }));
  fireEvent.click(first.getByRole("button", { name: "Guide me" }));
  await waitFor(() => expect(onError).toHaveBeenCalledWith("Temporary failure"));
  expect(first.queryByText("Recorded help: 1")).not.toBeInTheDocument();
  const requestId = vi.mocked(runReadingExtension).mock.calls[0][3].help_request_id;
  vi.mocked(runReadingExtension).mockResolvedValueOnce(help);
  fireEvent.click(first.getByRole("button", { name: "Guide me" }));
  await first.findByText("Recorded help: 1");
  expect(vi.mocked(runReadingExtension).mock.calls[1][3].help_request_id).toBe(requestId);
});

it("disables help for a selection in another section and hides unavailable actions", () => {
  const view = render(panel({ ...context, locator: 9 }));
  expect(screen.getAllByRole("button", { name: "Guide me" }).every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
  fireEvent.click(screen.getAllByRole("button", { name: "Guide me" })[0]);
  expect(runReadingExtension).not.toHaveBeenCalled();
  view.rerender(panel({ ...context, actions: [] }));
  expect(screen.queryByRole("button", { name: "Guide me" })).not.toBeInTheDocument();
});

it("ignores a late response after the quiz is replaced", async () => {
  let finish!: (value: ReadingExtensionResult) => void;
  vi.mocked(runReadingExtension).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  const view = render(panel());
  fireEvent.click(screen.getAllByRole("button", { name: "Guide me" })[0]);
  view.rerender(panel(context, { ...quiz, payload: { questions: [{ id: "new", prompt: "New question", choices: ["A", "B"], correct_choice_index: 0 }] } }));
  await act(async () => { finish(help); });
  expect(screen.getByText("New question")).toBeInTheDocument();
  expect(screen.queryByText("Look at the evidence.")).not.toBeInTheDocument();
  expect(screen.queryByText("Recorded help: 1")).not.toBeInTheDocument();
  expect(onError).not.toHaveBeenCalled();
});

it("rejects a result whose receipt belongs to another question", async () => {
  vi.mocked(runReadingExtension).mockResolvedValueOnce({ ...help, quiz_help: { question_id: "two", hints_used: 1 } });
  render(panel());
  fireEvent.click(screen.getAllByRole("button", { name: "Guide me" })[0]);
  await waitFor(() => expect(onError).toHaveBeenCalledWith("Failed to record help. Please try again."));
  expect(screen.queryByText("Recorded help: 1")).not.toBeInTheDocument();
});


it("passes the current workspace selection into help without replacing the quiz card", async () => {
  const originalScroll = HTMLElement.prototype.scrollIntoView;
  HTMLElement.prototype.scrollIntoView = vi.fn();
  try {
    vi.mocked(runReadingExtension).mockResolvedValueOnce(help);
    render(
      <ReadingActionsContext.Provider value={{
        ageMode: "default", speaking: false, busyKey: "", run: vi.fn(), stopSpeaking: vi.fn(), dismiss: vi.fn(),
        actions: [],
        helpActions: context.actions.map((entry) => ({ ...entry, key: "guided_learning:guide", label: "Guide me", needsSelection: true })),
        cards: [{ id: "card", key: "quiz:start", label: "Quiz", quote: "original quote", locator: 4,
          materialId: "material", status: "done", result: quiz }],
      }}>
        <ReadingActionCards selection={{ quote: "new verified selection", locator: 4 }} onFollowUp={vi.fn()} />
      </ReadingActionsContext.Provider>,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Guide me" })[0]);
    await screen.findByText("Recorded help: 1");
    expect(vi.mocked(runReadingExtension).mock.calls[0][3]).toMatchObject({
      selection: "new verified selection", locator: 4, question_id: "one",
    });
    expect(screen.getByRole("group", { name: "Question two" })).toBeInTheDocument();
  } finally {
    HTMLElement.prototype.scrollIntoView = originalScroll;
  }
});


function StartProviderQuiz() {
  const shared = useReadingActions();
  return <button onClick={() => {
    void shared?.run({ key: "quiz:start", label: "Quiz", needsSelection: false,
      extension: { id: "quiz", name: "Quiz", version: "1", protocol_version: "1", actions: [], result_types: ["quiz"] },
      action: { id: "start", label: "Quiz", trigger: "toolbar", requires: [] } });
  }}>Start provider quiz</button>;
}

it("derives card help from the real provider catalog despite chat menu filtering", async () => {
  const originalScroll = HTMLElement.prototype.scrollIntoView;
  HTMLElement.prototype.scrollIntoView = vi.fn();
  try {
    vi.mocked(listReadingExtensions).mockResolvedValue(context.actions.map(({ extension, action }) => ({ ...extension, actions: [action] })));
    vi.mocked(runReadingExtension).mockResolvedValueOnce(quiz).mockResolvedValueOnce(help);
    render(<ReadingActionsProvider materialId="material" locator={4}>
      <StartProviderQuiz />
      <ReadingActionCards selection={{ quote: "verified phrase", locator: 4 }} onFollowUp={vi.fn()} />
    </ReadingActionsProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Start provider quiz" }));
    const buttons = await screen.findAllByRole("button", { name: "Guide me" });
    fireEvent.click(buttons[0]);
    expect(await screen.findByText("Recorded help: 1")).toBeInTheDocument();
    expect(vi.mocked(runReadingExtension).mock.calls[1][3]).toMatchObject({ question_id: "one", locator: 4 });
  } finally {
    HTMLElement.prototype.scrollIntoView = originalScroll;
  }
});


it("prevents help while the answer is being saved", async () => {
  let finish!: (value: Awaited<ReturnType<typeof submitReadingQuizAnswers>>) => void;
  vi.mocked(submitReadingQuizAnswers).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  render(panel());
  const first = within(screen.getByRole("group", { name: "Question one" }));
  fireEvent.click(first.getByRole("button", { name: "A. A" }));
  expect(first.getByRole("button", { name: "Guide me" })).toBeDisabled();
  fireEvent.click(first.getByRole("button", { name: "Guide me" }));
  expect(runReadingExtension).not.toHaveBeenCalled();
  await act(async () => { finish({ answers: [{ question_id: "one", is_correct: false, result: "incorrect" }] }); });
  expect(first.getByRole("button", { name: "Guide me" })).not.toBeDisabled();
});
