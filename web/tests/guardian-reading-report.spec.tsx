import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { GuardianReadingReport } from "@/features/multi-user/components/GuardianReadingReport";
import type { GuardianReadingSummary } from "@/lib/guardian-api";
import { initI18n } from "@/i18n/init";

initI18n("en");
afterEach(cleanup);
const report = (): GuardianReadingSummary => ({
  reading_status: "available", quiz_status: "available", limit: 50,
  progress_total: 1,
  progress: [{ material_id: "m", latest_locator: 2, latest_percentage: 0.2, furthest_locator: 4, furthest_percentage: 0.4, updated_at: 1 }],
  activities: [], quiz_total: 58,
  quizzes: [{ id: 1, question_id: "q", material_id: "m", material_title: "Synthetic lesson", section_title: "Section", question: "Which statement?", is_correct: false, hints_used: 2, attempt_count: 3 }],
});
it("shows reading position, incorrect answers and recorded assistance without write controls", () => {
  render(<GuardianReadingReport reading={report()} />);
  expect(screen.getByText("Synthetic lesson")).toBeTruthy();
  expect(screen.getByText(/Current section 2/).textContent).toContain("40%");
  expect(screen.getByText(/Incorrect/).textContent).toContain("2 recorded hints");
  expect(screen.getByText("Showing 1 of 58 quiz records")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});
it("does not label zero recorded hints as independent mastery", () => {
  const value = report();
  value.quizzes[0].is_correct = null;
  value.quizzes[0].hints_used = 0;
  render(<GuardianReadingReport reading={value} />);
  expect(screen.getByText(/Not graded/).textContent).toContain("No question-linked help recorded");
  expect(screen.getByText("Reading position and quiz results do not establish independent mastery.")).toBeTruthy();
});
it("distinguishes migration and uninitialized records from zero-result reports", () => {
  const value = report();
  value.reading_status = "migration_required";
  value.quiz_status = "not_initialized";
  render(<GuardianReadingReport reading={value} />);
  expect(screen.getByText(/Reading records need migration/)).toBeTruthy();
  expect(screen.getByText("Quiz records have not been initialized.")).toBeTruthy();
  expect(screen.queryByText(/Showing .* records/)).toBeNull();
});
it("distinguishes two materials that have no quiz records", () => {
  const value = report();
  value.quizzes = [];
  value.quiz_total = 0;
  value.progress_total = 2;
  value.progress = [
    { ...value.progress[0], material_id: "first", material_title: "First lesson" },
    { ...value.progress[0], material_id: "second" },
  ];
  render(<GuardianReadingReport reading={value} />);
  expect(screen.getByText("First lesson")).toBeTruthy();
  expect(screen.getByText("Reading material second")).toBeTruthy();
});
