import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import SpaceQuestionsPage from "@/app/(utility)/space/questions/page";
import PracticeRoutePage from "@/app/(workspace)/learning/practice/page";
import { initI18n } from "@/i18n/init";
import * as api from "@/lib/practice-api";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("course=course-a&workspace=work-a&view=mistakes"),
  useRouter: () => ({ replace }),
}));
vi.mock("@/components/space/question-bank", () => ({
  QuestionBankSection: ({
    mistakesOnly,
    onPractice,
  }: {
    mistakesOnly: boolean;
    onPractice?: (ids: number[]) => void;
  }) => (
    <div>
      {mistakesOnly ? "Stored mistakes" : "Stored questions"}
      {onPractice && <button onClick={() => onPractice([1])}>Practice this page</button>}
    </div>
  ),
}));
vi.mock("@/lib/practice-api", async original => ({
  ...(await original<typeof api>()),
  getPracticeSummary: vi.fn(),
  getPracticeQuestion: vi.fn(),
  getPracticeAnalytics: vi.fn(),
}));
initI18n("en");
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    }
  );
  vi.mocked(api.getPracticeSummary).mockResolvedValue({
    total: 67,
    mistakes: 42,
    due: 38,
    overdue: 38,
    reviewed_today: 4,
    next_due_at: null,
    day_end: 100,
    timezone: "UTC",
  });
  vi.mocked(api.getPracticeAnalytics).mockResolvedValue({
    timezone: "UTC",
    days: 30,
    start_date: "2026-09-19",
    end_date: "2026-09-19",
    updated_at: 100,
    totals: { questions: 2, mistakes: 1, reviews: 4 },
    daily: [{ date: "2026-09-19", questions: 2, mistakes: 1, reviews: 4 }],
    sources: [],
  });
});

it("keeps Learning Space in its own collection route with scoped imports and no daily review panels", async () => {
  render(<SpaceQuestionsPage />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Question Bank");
  expect(await screen.findByRole("tab", { name: "Mistakes42" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(screen.getByText("Stored mistakes")).toBeVisible();
  expect(screen.queryByRole("region", { name: "Practice activity" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Today's review" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Practice this page" })).toBeVisible();
  expect(api.getPracticeAnalytics).not.toHaveBeenCalled();
  expect(api.getPracticeSummary).toHaveBeenCalledWith("course-a");

  fireEvent.click(screen.getByRole("button", { name: "Import questions" }));
  expect(screen.getByRole("combobox", { name: "Import into" })).toHaveValue("mistakes");
  expect(screen.getByLabelText(/Choose a question file/)).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "Question Bank67" }));
  expect(replace).toHaveBeenLastCalledWith(
    "/space/questions?course=course-a&workspace=work-a&view=bank",
    { scroll: false }
  );
  fireEvent.click(screen.getByRole("button", { name: "Show every course" }));
  expect(replace).toHaveBeenLastCalledWith("/space/questions?workspace=work-a&view=mistakes");
});

it("retains analytics, daily review and collections in Personalized Learning", async () => {
  render(<PracticeRoutePage />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Practice");
  expect(await screen.findByRole("button", { name: /New questions\s*2/ })).toBeVisible();
  expect(screen.getByRole("region", { name: "Today's review" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Start today's review" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Practice this page" })).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "Question Bank67" }));
  expect(replace).toHaveBeenLastCalledWith(
    "/learning/practice?course=course-a&workspace=work-a&view=bank",
    { scroll: false }
  );
});


it("starts manual practice from the collection and returns to the same course and mistakes view", async () => {
  vi.mocked(api.getPracticeQuestion).mockResolvedValue({
    entry: {
      id: 1, session_id: "lesson", session_title: "Lesson", turn_id: "", question_id: "q1",
      question: "Which ocean?", question_type: "single_choice", options: { A: "Pacific", B: "Atlantic" },
      correct_answer: "B", explanation: "Reference explanation", difficulty: "", user_answer: "",
      source: "deep_question", material_id: "", material_title: "", section_id: "", section_title: "",
      score_trend: "new", is_correct: false, resolved: false, bookmarked: false, followup_session_id: "", created_at: 1, updated_at: 1,
    },
    state: { version: 2, review_count: 1, is_mistake: true, due_at: 100 },
  });
  render(<SpaceQuestionsPage />);
  await screen.findByRole("tab", { name: "Mistakes42" });
  fireEvent.click(screen.getByRole("button", { name: "Practice this page" }));
  expect(await screen.findByRole("button", { name: "Back to library" })).toBeVisible();
  expect(api.getPracticeQuestion).toHaveBeenCalledWith(1, undefined);
  expect(screen.queryByText("Stored mistakes")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Back to library" }));
  expect(await screen.findByText("Stored mistakes")).toBeVisible();
  expect(screen.getByRole("tab", { name: "Mistakes42" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("This course")).toBeVisible();
  expect(replace).not.toHaveBeenCalled();
  expect(api.getPracticeSummary).toHaveBeenLastCalledWith("course-a");
});
