import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ObjectiveDetail } from "@/components/space/learning/ObjectiveDetail";
import { initI18n } from "@/i18n/init";
import type { ObjectiveReport } from "@/lib/learning-api";

initI18n("en");

function report(overrides: Partial<ObjectiveReport> = {}): ObjectiveReport {
  return {
    id: "kp1",
    name: "Why XOR matters",
    type: "concept",
    module_name: "Module 1",
    status: "learning",
    gate: "qualitative",
    mastered: false,
    assessed_mastered: false,
    mastery_source: "",
    override_note: "",
    // Quiz accuracy, which the qualitative gate never reads.
    mastery: 1,
    threshold: 1,
    attempts: [
      {
        question_id: "q1",
        prompt: "Why does XOR matter?",
        answer: "it is not linearly separable",
        is_correct: true,
        error_type: "",
        at: 1_700_000_000,
      },
    ],
    correct_count: 1,
    explanation: "",
    review: null,
    errors: [],
    ...overrides,
  };
}

describe("objective gate bar", () => {
  it("does not draw quiz accuracy as progress toward a qualitative gate", () => {
    // The reading that made this necessary: mastery 1.0 against threshold 1.0
    // on an objective that is not mastered. Shown as a bar it says "full, yet
    // not cleared" — beside an outline dot that is correctly still hollow.
    render(<ObjectiveDetail report={report()} zh={false} />);

    expect(screen.getByText("0%")).toBeTruthy();
    expect(screen.queryByText("100%")).toBeNull();
    expect(
      screen.getByText(/Practice questions do not open this gate/),
    ).toBeTruthy();
  });

  it("fills the bar once the qualitative gate actually opens", () => {
    render(
      <ObjectiveDetail
        report={report({
          mastered: true,
          assessed_mastered: true,
          status: "mastered",
          mastery_source: "system",
        })}
        zh={false}
      />,
    );

    expect(screen.getByText("100%")).toBeTruthy();
    expect(
      screen.queryByText(/Practice questions do not open this gate/),
    ).toBeNull();
  });

  it("still reports real progress against a quantitative gate", () => {
    render(
      <ObjectiveDetail
        report={report({
          type: "memory",
          gate: "quantitative",
          mastery: 0.5,
          threshold: 0.9,
        })}
        zh={false}
      />,
    );

    expect(screen.getByText("50%")).toBeTruthy();
    expect(
      screen.queryByText(/Practice questions do not open this gate/),
    ).toBeNull();
  });
});
