import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { initI18n } from "@/i18n/init";
import QuizVerdictSummary from "@/components/quiz/QuizVerdictSummary";
import {
  parseQuizVerdict,
  resolveQuizAssessment,
  type QuizVerdict,
} from "@/lib/quiz-verdict";

initI18n("en");

const judged: QuizVerdict = {
  result: "partial",
  is_correct: null,
  final: true,
  confidence: 0.9,
  steps: [
    { label: "Goodwill", ok: true, comment: "200 is right." },
    { label: "Minority interest", ok: false, comment: "Use fair value." },
  ],
  awarded_points: 3,
  max_points: 5,
};

describe("parseQuizVerdict", () => {
  it("keeps a valid final verdict with points and steps", () => {
    expect(parseQuizVerdict(judged)).toEqual(judged);
  });

  it("rejects unknown results and non-objects", () => {
    expect(parseQuizVerdict({ result: "probably" })).toBeNull();
    expect(parseQuizVerdict("correct")).toBeNull();
    expect(parseQuizVerdict(null)).toBeNull();
  });

  it("requires a known result and a boolean final", () => {
    expect(parseQuizVerdict({ result: "correct" })).toBeNull();
    expect(parseQuizVerdict({ result: "correct", final: "yes" })).toBeNull();
  });

  it("drops malformed steps", () => {
    const verdict = parseQuizVerdict({
      ...judged,
      steps: [{ label: "ok", ok: true }, { label: 3 }, { label: "x", ok: null }, "x"],
    });
    expect(verdict?.steps).toEqual([{ label: "ok", ok: true, comment: "" }]);
  });
});

describe("resolveQuizAssessment", () => {
  const base = { exactCorrect: false, objective: false, hasImages: false };

  it("keeps exact matching authoritative for objective questions", () => {
    const correct = { ...judged, result: "correct" as const, is_correct: true };
    expect(
      resolveQuizAssessment({ ...base, objective: true, verdict: correct }),
    ).toEqual({ is_correct: false });
  });

  it("never lets the judge downgrade an exact match", () => {
    const wrong = { ...judged, result: "incorrect" as const, is_correct: false };
    expect(
      resolveQuizAssessment({ ...base, exactCorrect: true, verdict: wrong }),
    ).toEqual({ is_correct: true });
  });

  it("uses a final verdict for answers exact matching cannot grade", () => {
    expect(resolveQuizAssessment({ ...base, verdict: judged })).toEqual({
      is_correct: false,
      result: "partial",
    });
    expect(
      resolveQuizAssessment({
        ...base,
        hasImages: true,
        verdict: { ...judged, result: "correct", is_correct: true },
      }),
    ).toEqual({ is_correct: true, result: "correct" });
  });

  it("ignores a verdict that is not final", () => {
    const unsure = { ...judged, result: "correct" as const, final: false };
    expect(resolveQuizAssessment({ ...base, verdict: unsure })).toEqual({
      is_correct: false,
    });
  });

  it("keeps photo answers ungraded until a final verdict exists", () => {
    expect(
      resolveQuizAssessment({ ...base, hasImages: true, verdict: null }),
    ).toEqual({ is_correct: false, result: "ungraded" });
    expect(
      resolveQuizAssessment({
        ...base,
        hasImages: true,
        verdict: {
          result: "ungraded",
          is_correct: null,
          final: false,
          confidence: 0,
          steps: [],
          reason: "vision_unavailable",
        },
      }),
    ).toEqual({ is_correct: false, result: "ungraded" });
  });
});

describe("QuizVerdictSummary", () => {
  it("hides the result badge and points when exact matching decided", () => {
    render(<QuizVerdictSummary verdict={judged} showResult={false} />);
    expect(screen.queryByText("Partially correct")).toBeNull();
    expect(screen.queryByText("3 / 5 points")).toBeNull();
    expect(screen.getByText("Minority interest")).toBeInTheDocument();
  });

  it("renders badge, points and step feedback", () => {
    render(<QuizVerdictSummary verdict={judged} />);
    expect(screen.getByText("Partially correct")).toBeInTheDocument();
    expect(screen.getByText("3 / 5 points")).toBeInTheDocument();
    const steps = screen.getByRole("list", { name: "Solution steps" });
    expect(steps.querySelectorAll("li")).toHaveLength(2);
    expect(screen.getByText("Minority interest")).toBeInTheDocument();
    expect(screen.getByText(/Use fair value\./)).toBeInTheDocument();
  });

  it("explains why an answer was not graded", () => {
    render(
      <QuizVerdictSummary
        verdict={{
          result: "ungraded",
          is_correct: null,
          final: false,
          confidence: 0,
          steps: [],
          reason: "vision_unavailable",
        }}
      />,
    );
    expect(screen.getByText("Not graded")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This model cannot read images, so the photo answer was not graded.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("list")).toBeNull();
  });
});
