import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AskUserOptions } from "@/components/chat/home/AskUserOptions";
import type { AskUserCardData } from "@/components/chat/home/AskUserOptions";
import { initI18n } from "@/i18n/init";

initI18n("en");

const card = (overrides: Partial<AskUserCardData> = {}): AskUserCardData => ({
  payload: {
    intro: "Which path?",
    questions: [
      {
        id: "which",
        prompt: "Where should we pick up?",
        header: null,
        multi_select: false,
        options: [{ label: "Advanced route", description: "15 goals" }],
        allow_free_text: true,
        placeholder: null,
      },
    ],
  },
  answers: null,
  resolved: false,
  ...overrides,
});

describe("a card the model is still writing", () => {
  it("says so, and refuses every answer until the question is finished", () => {
    const submit = vi.fn();
    render(<AskUserOptions data={card({ streaming: true })} onSubmit={submit} />);

    expect(screen.getByText("Writing the question…")).toBeVisible();

    const option = screen.getByRole("button", { name: /Advanced route/ });
    expect(option).toBeDisabled();
    const submitButton = screen.getByRole("button", { name: "Submit" });
    expect(submitButton).toBeDisabled();

    // Even a click delivered straight to the element must not reach the
    // backend: the turn has not dispatched this call yet, so there is
    // nothing waiting for an answer to it.
    fireEvent.click(option);
    fireEvent.click(submitButton);
    expect(submit).not.toHaveBeenCalled();
  });

  it("stands the card up on its intro alone, before any question arrives", () => {
    render(
      <AskUserOptions
        data={card({
          streaming: true,
          payload: { intro: "Which path?", questions: [] },
        })}
        onSubmit={() => undefined}
      />,
    );

    expect(screen.getByText("Which path?")).toBeVisible();
    expect(screen.getByText("Writing the question…")).toBeVisible();
    // No question yet, so nothing claims to be answerable.
    expect(screen.queryByText("Where should we pick up?")).toBeNull();
  });

  it("becomes answerable the moment the call is dispatched", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <AskUserOptions data={card({ streaming: true })} onSubmit={submit} />,
    );
    rerender(<AskUserOptions data={card()} onSubmit={submit} />);

    expect(screen.queryByText("Writing the question…")).toBeNull();
    await user.click(screen.getByRole("button", { name: /Advanced route/ }));
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).toHaveBeenCalledWith({
      text: "Advanced route",
      answers: [{ questionId: "which", text: "Advanced route" }],
    });
  });
});
