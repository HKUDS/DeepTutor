import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ComposerChoiceDock } from "@/components/space/learning/OutlineDecisionDialog";
import { initI18n } from "@/i18n/init";

initI18n("en");

describe("ComposerChoiceDock", () => {
  it("can be put away again after it opens", async () => {
    render(
      <ComposerChoiceDock
        testId="dock"
        summary="A question needs your answer"
        confirmLabel="Answer this question"
      >
        <p>Question body</p>
      </ComposerChoiceDock>,
    );

    expect(screen.queryByText("Question body")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Answer this question" }));
    expect(screen.getByText("Question body")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByText("Question body")).toBeNull();
    // The way back in stays, so closing is a collapse, not a dead end.
    expect(screen.getByRole("button", { name: "Answer this question" })).toBeInTheDocument();
  });
});
