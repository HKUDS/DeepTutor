import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { MasteryQuestionCard } from "@/components/chat/home/MasteryQuestionCard";
import { ComposerChoiceDock } from "@/components/space/learning/OutlineDecisionDialog";
import { initI18n } from "@/i18n/init";
import { REPLY_NOT_DELIVERED } from "@/lib/ask-user-state";
import type { MasteryQuestion } from "@/lib/mastery-question";

initI18n("en");

const question = (questionId: string): MasteryQuestion => ({
  questionId,
  prompt: "When do you write a workflow?",
  questionType: "short",
  objectiveName: "Workflows",
  difficulty: "medium",
  attempt: 1,
  options: [],
  allowFreeText: true,
});

/**
 * The dock as ``MasteryStudy`` mounts it: one card, keyed by the question id.
 *
 * The card closes by unmounting (the dock only shows while a question is open),
 * so the two behaviours that keep it honest are that a re-posed question is a
 * fresh card, and that a send which never landed reopens it.
 */
function Dock({
  question: q,
  onSubmit = () => true,
}: {
  question: MasteryQuestion;
  onSubmit?: (payload: { text?: string }) => boolean | Promise<boolean>;
}) {
  return (
    <ComposerChoiceDock
      testId="mastery-answer-dock"
      summary="A question needs your answer"
      confirmLabel="Answer this question"
    >
      <MasteryQuestionCard
        key={q.questionId}
        question={q}
        grade={null}
        answered={false}
        submittedAnswer=""
        onSubmit={onSubmit}
        onSkip={() => true}
      />
    </ComposerChoiceDock>
  );
}

describe("mastery answer dock", () => {
  it("gives a re-posed question a fresh card instead of a stuck one", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Dock question={question("q-1")} />);
    await user.click(
      screen.getByRole("button", { name: "Answer this question" }),
    );

    await user.type(
      screen.getByRole("textbox"),
      "When the steps are enumerable.",
    );
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(screen.getByText("Sending your answers…")).toBeInTheDocument();

    // The tutor re-posed the question (a new id, same prompt): the card must
    // not carry the previous submission's in-flight state into it.
    rerender(<Dock question={question("q-2")} />);

    expect(screen.queryByText("Sending your answers…")).toBeNull();
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });

  it("reopens the card when the answer never reached a waiting turn", async () => {
    const user = userEvent.setup();
    render(
      <Dock
        question={question("q-1")}
        onSubmit={() => Promise.resolve(false)}
      />,
    );
    await user.click(
      screen.getByRole("button", { name: "Answer this question" }),
    );

    await user.type(
      screen.getByRole("textbox"),
      "When the steps are enumerable.",
    );
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText(REPLY_NOT_DELIVERED)).toBeInTheDocument();
    expect(screen.queryByText("Sending your answers…")).toBeNull();
  });
});
