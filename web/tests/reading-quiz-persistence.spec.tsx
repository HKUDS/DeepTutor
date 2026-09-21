import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ReadingExtensionBar } from "@/components/reading/ReadingExtensionBar";
import { initI18n } from "@/i18n/init";
import {
  listReadingExtensions,
  runReadingExtension,
  submitReadingQuizAnswers,
} from "@/lib/reading-api";
vi.mock("@/lib/reading-api", () => ({
  listReadingExtensions: vi.fn(),
  runReadingExtension: vi.fn(),
  submitReadingQuizAnswers: vi.fn(),
}));
initI18n("en");
beforeEach(() => {
  vi.mocked(listReadingExtensions).mockResolvedValue([
    {
      id: "quiz",
      name: "Quiz",
      version: "1",
      protocol_version: "1",
      actions: [{ id: "start", label: "Quiz me", trigger: "toolbar", requires: [] }],
      result_types: ["quiz"],
    },
  ]);
  vi.mocked(runReadingExtension).mockResolvedValue({
    type: "quiz",
    title: "",
    message: "",
    payload: {
      questions: [
        {
          id: "quiz-1",
          prompt: "Which ocean?",
          choices: ["Pacific", "Atlantic"],
          correct_choice_index: 1,
        },
      ],
    },
  });
});
it("waits for saving, uses the server verdict, and preserves the original locator after scrolling", async () => {
  const onError = vi.fn();
  let finish!: (value: Awaited<ReturnType<typeof submitReadingQuizAnswers>>) => void;
  vi.mocked(submitReadingQuizAnswers).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(
    <ReadingExtensionBar materialId="material-1" locator={4} onError={onError} />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Quiz me" }));
  const answer = await screen.findByRole("button", { name: "B. Atlantic" });
  view.rerender(<ReadingExtensionBar materialId="material-1" locator={9} onError={onError} />);
  fireEvent.click(answer);
  expect(answer).toBeDisabled();
  expect(screen.queryByText("Correct")).not.toBeInTheDocument();
  expect(submitReadingQuizAnswers).toHaveBeenCalledWith("material-1", {
    locator: 4,
    session_id: "",
    answers: [{ question_id: "quiz-1", selected_index: 1 }],
  });
  await act(async () => {
    finish([{ question_id: "quiz-1", is_correct: false, result: "incorrect" }]);
  });
  expect(await screen.findByText("Incorrect")).toBeInTheDocument();
  expect(answer).not.toBeDisabled();
  expect(onError).not.toHaveBeenCalled();
});
it("keeps a failed answer retryable without showing a successful grade", async () => {
  const onError = vi.fn();
  vi.mocked(submitReadingQuizAnswers).mockRejectedValueOnce(new Error("Save failed"));
  render(<ReadingExtensionBar materialId="material-1" locator={4} onError={onError} />);
  fireEvent.click(await screen.findByRole("button", { name: "Quiz me" }));
  const answer = await screen.findByRole("button", { name: "B. Atlantic" });
  fireEvent.click(answer);
  await waitFor(() => expect(onError).toHaveBeenCalledWith("Save failed"));
  expect(screen.queryByText("Correct")).not.toBeInTheDocument();
  expect(answer).toHaveAttribute("aria-pressed", "false");
  expect(answer).not.toBeDisabled();
});
