import { render, screen } from "@testing-library/react";
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
