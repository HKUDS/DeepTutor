import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MasteryQuestionCard } from "@/components/chat/home/MasteryQuestionCard";
import { initI18n } from "@/i18n/init";
import type { MasteryQuestion } from "@/lib/mastery-question";

initI18n("en");

const question = (overrides: Partial<MasteryQuestion> = {}): MasteryQuestion => ({
  questionId: "q-free",
  prompt: "Explain the difference between precision and recall.",
  questionType: "short",
  objectiveName: "Evaluation metrics",
  difficulty: "medium",
  attempt: 1,
  options: [],
  allowFreeText: true,
  ...overrides,
});

describe("MasteryQuestionCard", () => {
  it("shows original evidence and assisted meaning without exposing a reference key", () => {
    render(<MasteryQuestionCard question={question({ visual: { task: "identification", answerCues: "visible", keyStatus: "unverified", hintsUsed: 1, sources: [{ imageUrl: "/api/knowledge-bases/kb/visual-assets/known", url: "/api/knowledge-bases/kb/files/book.pdf#page=4", sourcePath: "book.pdf", page: 4 }] } })} grade={null} answered={false} submittedAnswer="" onSubmit={() => true} />);
    expect(screen.getByRole("img", { name: "Original source evidence" })).toHaveAttribute("src", "/api/knowledge-bases/kb/visual-assets/known");
    expect(screen.getByText("Guided visual practice — this does not demonstrate independent mastery.")).toBeInTheDocument();
    expect(screen.getByText("The reference key is uncertain. This practice will remain ungraded.")).toBeInTheDocument();
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByRole("alert")).toHaveTextContent("The source image is unavailable");
  });
  it("keeps uncertain grades neutral and sends a source-review challenge", async () => {
    const user = userEvent.setup();
    const onChallenge = vi.fn(() => true);
    render(<MasteryQuestionCard question={question()} grade={{ questionId: "q-free", isCorrect: false, result: "ungraded", learnerAnswer: "ambiguous", correctLabel: "", correctBody: "", explanation: "Source evidence needs clarification." }} answered submittedAnswer="" onSubmit={() => true} onChallenge={onChallenge} />);
    expect(screen.getByText("Ungraded — mastery unchanged")).toBeInTheDocument();
    expect(screen.queryByText("Not quite")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Review or challenge this assessment" }));
    expect(onChallenge).toHaveBeenCalledWith("q-free");
  });
  it("enables submit from a free-text-only question", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => true);
    render(
      <MasteryQuestionCard
        question={question()}
        grade={null}
        answered={false}
        submittedAnswer=""
        onSubmit={onSubmit}
      />,
    );

    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();

    await user.type(screen.getByRole("textbox"), "Precision measures exactness");
    expect(submit).toBeEnabled();

    await user.click(submit);
    expect(onSubmit).toHaveBeenCalledWith({
      text: "Precision measures exactness",
      answers: [
        {
          questionId: "q-free",
          text: "Precision measures exactness",
        },
      ],
    });
  });

  it("keeps explicit free text working alongside choices", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => true);
    render(
      <MasteryQuestionCard
        question={question({
          questionId: "q-choice",
          options: [{ label: "A", body: "Precision measures exactness" }],
        })}
        grade={null}
        answered={false}
        submittedAnswer=""
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Answer in my own words/ }));
    await user.type(screen.getByRole("textbox"), "They answer different errors");
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(onSubmit).toHaveBeenCalledWith({
      text: "They answer different errors",
      answers: [
        {
          questionId: "q-choice",
          text: "They answer different errors",
        },
      ],
    });
  });
});
