import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import QuizBlock from "@/app/(workspace)/learning/books/components/blocks/QuizBlock";
import type { Block } from "@/lib/book-types";
import { initI18n } from "@/i18n/init";

vi.mock("@/components/common/MarkdownRenderer", () => ({
  default: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

initI18n("en");

const quizBlock = {
  id: "blk_quiz",
  type: "quiz",
  status: "ready",
  title: "",
  params: {},
  payload: {
    questions: [
      {
        question_id: "q_1",
        question: "Pick the correct option",
        question_type: "choice",
        options: { A: "Alpha", B: "Beta", C: "Gamma", D: "Delta" },
        correct_answer: "B",
        explanation: "Beta is correct.",
      },
      {
        question_id: "q_2",
        question: "True or false: this statement holds.",
        question_type: "concept",
        options: {},
        correct_answer: "false",
        explanation: "It does not hold.",
      },
    ],
  },
  source_anchors: [],
  metadata: {},
  error: "",
  created_at: 0,
  updated_at: 0,
} as unknown as Block;

function cardFor(question: string): HTMLElement {
  const card = screen.getByText(question).closest("div.rounded-xl");
  if (!card) throw new Error("question card not found");
  return card as HTMLElement;
}

it("renders choice options as buttons and grades the revealed choice", () => {
  const onAttempt = vi.fn();
  render(<QuizBlock block={quizBlock} onAttempt={onAttempt} />);

  const card = cardFor("Pick the correct option");
  const optionButtons = within(card)
    .getAllByRole("button")
    .filter((button) => /^[A-D]\./.test(button.textContent || ""));
  expect(optionButtons).toHaveLength(4);

  fireEvent.click(within(card).getByRole("button", { name: /^B\./ }));
  fireEvent.click(within(card).getByRole("button", { name: "Reveal answer" }));

  expect(onAttempt).toHaveBeenCalledWith(
    quizBlock,
    expect.objectContaining({ questionId: "q_1", userAnswer: "B", isCorrect: true }),
  );
});

it("renders concept questions as true/false buttons and grades them", () => {
  const onAttempt = vi.fn();
  render(<QuizBlock block={quizBlock} onAttempt={onAttempt} />);

  const card = cardFor("True or false: this statement holds.");
  fireEvent.click(within(card).getByRole("button", { name: "False" }));
  fireEvent.click(within(card).getByRole("button", { name: "Reveal answer" }));

  expect(onAttempt).toHaveBeenCalledWith(
    quizBlock,
    expect.objectContaining({
      questionId: "q_2",
      userAnswer: "false",
      isCorrect: true,
    }),
  );
});