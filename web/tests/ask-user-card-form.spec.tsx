import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AskUserOptions } from "@/components/chat/home/AskUserOptions";
import type {
  AskUserCardData,
  AskUserQuestion,
} from "@/components/chat/home/AskUserOptions";
import { initI18n } from "@/i18n/init";

initI18n("en");

function question(
  id: string,
  prompt: string,
  labels: string[],
  overrides: Partial<AskUserQuestion> = {},
): AskUserQuestion {
  return {
    id,
    prompt,
    header: null,
    multi_select: false,
    options: labels.map((label) => ({ label, description: null })),
    allow_free_text: true,
    placeholder: null,
    ...overrides,
  };
}

function card(questions: AskUserQuestion[]): AskUserCardData {
  return {
    payload: { intro: null, questions },
    answers: null,
    resolved: false,
  };
}

const pace = question("pace", "How fast should we go?", [
  "Steady pace",
  "Deep dive",
]);

describe("picking an option by its number", () => {
  it("selects the row carrying that number, and still waits for Submit", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    render(<AskUserOptions data={card([pace])} onSubmit={submit} />);

    await user.keyboard("2");
    expect(screen.getByRole("button", { name: /Deep dive/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // The number picks; it does not answer for the user.
    expect(submit).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).toHaveBeenCalledWith({
      text: "Deep dive",
      answers: [{ questionId: "pace", text: "Deep dive" }],
    });
  });

  it("ignores a number no option carries", async () => {
    const user = userEvent.setup();
    render(<AskUserOptions data={card([pace])} onSubmit={vi.fn()} />);

    await user.keyboard("7");
    for (const label of [/Steady pace/, /Deep dive/]) {
      expect(screen.getByRole("button", { name: label })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    }
  });

  it("leaves the digit alone once the user is writing their own reply", async () => {
    const user = userEvent.setup();
    render(<AskUserOptions data={card([pace])} onSubmit={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /Something else/ }));
    await user.keyboard("2");

    // The keystroke belongs to the box that has focus, not to the list.
    expect(screen.getByRole("textbox")).toHaveValue("2");
    expect(screen.getByRole("button", { name: /Deep dive/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});

describe("declining a question", () => {
  it("submits the only question empty, which the backend reads as skipped", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    render(<AskUserOptions data={card([pace])} onSubmit={submit} />);

    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(submit).toHaveBeenCalledWith({
      text: "",
      answers: [{ questionId: "pace", text: "" }],
    });
  });

  it("drops the pick it just cleared rather than sending it as the answer", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    render(<AskUserOptions data={card([pace])} onSubmit={submit} />);

    await user.keyboard("1");
    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(submit).toHaveBeenCalledWith({
      text: "",
      answers: [{ questionId: "pace", text: "" }],
    });
  });

  it("walks forward through a multi-question card and submits at the end", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    const depth = question("depth", "How deep?", ["Overview", "Everything"], {
      header: "Depth",
    });
    render(<AskUserOptions data={card([pace, depth])} onSubmit={submit} />);

    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(screen.getByText("How deep?")).toBeVisible();
    expect(submit).not.toHaveBeenCalled();

    // Nothing left to move on to, so declining the last one finishes the card
    // instead of bouncing back to the question already declined.
    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(submit).toHaveBeenCalledWith({
      text: "",
      answers: [
        { questionId: "pace", text: "" },
        { questionId: "depth", text: "" },
      ],
    });
  });
});

describe("the shape of the card", () => {
  it("draws one rule, between the answering area and the controls", () => {
    const { container } = render(
      <AskUserOptions data={card([pace])} onSubmit={vi.fn()} />,
    );

    // Writing your own answer is one more way to answer, so it reads as the
    // last row of the list rather than a band behind a rule of its own. That
    // leaves exactly one rule in the card: the one under everything you can
    // answer with, above the controls that end the question.
    const rules = container.querySelectorAll('[class*="border-t"]');
    expect(rules).toHaveLength(1);
    const rule = rules[0];
    for (const name of ["Steady pace", "Something else…"]) {
      const row = screen.getByRole("button", { name: new RegExp(name) });
      expect(
        row.compareDocumentPosition(rule) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
    // Declining and answering both end the question, so Skip sits with Submit.
    expect(rule.contains(screen.getByRole("button", { name: "Skip" }))).toBe(
      true,
    );
    expect(rule.contains(screen.getByRole("button", { name: "Submit" }))).toBe(
      true,
    );
  });
});

describe("the answered card", () => {
  it("is the question, greyed, with the answer under it — no heading to open", () => {
    render(
      <AskUserOptions
        data={{
          payload: { intro: null, questions: [pace] },
          answers: [{ questionId: "pace", text: "Deep dive" }],
          resolved: true,
        }}
        onSubmit={vi.fn()}
      />,
    );

    const answered = screen.getByTestId("ask-user-answers");
    expect(answered).toHaveTextContent("How fast should we go?");
    expect(answered).toHaveTextContent("Deep dive");
    // Two lines are not worth a disclosure: nothing to expand, nothing to
    // count.
    expect(screen.queryByText("Your answers")).toBeNull();
    expect(answered.querySelector("button")).toBeNull();
  });

  it("says a skipped question was skipped", () => {
    render(
      <AskUserOptions
        data={{
          payload: { intro: null, questions: [pace] },
          answers: [{ questionId: "pace", text: "" }],
          resolved: true,
        }}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByTestId("ask-user-answers")).toHaveTextContent(
      "(skipped)",
    );
  });

  it("keeps the disclosure for the surface that asked for one", async () => {
    const user = userEvent.setup();
    render(
      <AskUserOptions
        data={{
          payload: { intro: null, questions: [pace] },
          answers: [{ questionId: "pace", text: "Deep dive" }],
          resolved: true,
        }}
        onSubmit={vi.fn()}
        collapsible
        defaultCollapsed
      />,
    );

    expect(screen.queryByText("Deep dive")).toBeNull();
    await user.click(screen.getByRole("button", { name: /Your answers/ }));
    expect(screen.getByText("Deep dive")).toBeVisible();
  });
});
