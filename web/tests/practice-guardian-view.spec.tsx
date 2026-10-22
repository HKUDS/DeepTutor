import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import PracticeRoutePage from "@/app/(workspace)/learning/practice/page";
import { initI18n } from "@/i18n/init";
import * as api from "@/lib/practice-api";
import * as guardianApi from "@/lib/guardian-api";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("learner=u_learner1&stats_metric=reading"),
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("@/lib/practice-api", async original => ({
  ...(await original<typeof api>()),
  getPracticeSummary: vi.fn(),
  getPracticeQueue: vi.fn(),
  getPracticeQuestion: vi.fn(),
  getPracticeAnalytics: vi.fn(),
}));
vi.mock("@/lib/guardian-api", async original => ({
  ...(await original<typeof guardianApi>()),
  getGuardianReport: vi.fn(),
}));
initI18n("en");

const summary = {
  total: 12,
  mistakes: 5,
  due: 4,
  overdue: 1,
  reviewed_today: 2,
  next_due_at: null,
  day_end: 100,
  timezone: "UTC",
};
const queueItem: api.PracticeQuestion = {
  content_workspace_id: "",
  entry: {
    id: 7,
    session_id: "lesson",
    session_title: "Lesson",
    turn_id: "",
    question_id: "q7",
    question: "Which planet is largest?",
    question_type: "single_choice",
    options: { A: "Earth", B: "Jupiter" },
    correct_answer: "B",
    explanation: "Jupiter is the largest planet.",
    difficulty: "easy",
    user_answer: "A",
    source: "immersive_reading",
    material_id: "rm_book",
    material_title: "Book",
    section_id: "",
    section_title: "",
    score_trend: "new",
    is_correct: false,
    resolved: false,
    bookmarked: false,
    followup_session_id: "",
    created_at: 1,
    updated_at: 1,
  },
  state: { version: 0, review_count: 1, is_mistake: true, due_at: 50 },
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    }
  );
  vi.mocked(guardianApi.getGuardianReport).mockResolvedValue({
    learner: { id: "u_learner1", username: "baby", disabled: false },
    assigned_materials: [],
    grant_summary: { model_count: 0, knowledge_base_count: 0, skill_count: 0 },
  });
  vi.mocked(api.getPracticeSummary).mockResolvedValue(summary);
  vi.mocked(api.getPracticeQueue).mockResolvedValue([queueItem]);
  vi.mocked(api.getPracticeAnalytics).mockResolvedValue({
    timezone: "UTC",
    days: 30,
    start_date: "2026-10-19",
    end_date: "2026-10-19",
    updated_at: 100,
    totals: { questions: 3, mistakes: 1, reviews: 2, reading_seconds: 7200 },
    daily: [
      { date: "2026-10-19", questions: 3, mistakes: 1, reviews: 2, reading_seconds: 7200 },
    ],
    sources: [],
    materials: [{ material_id: "rm_book", reading_seconds: 7200 }],
  });
});

it("renders a read-only banner and never offers write controls", async () => {
  render(<PracticeRoutePage />);
  expect(await screen.findByRole("note")).toHaveTextContent("read-only");
  expect(screen.getByText(/baby's practice/i)).toBeInTheDocument();
  // Wait for the learner-scoped data to land before asserting on the calls.
  expect(await screen.findByRole("button", { name: /Reading minutes\s*120/ })).toBeVisible();
  // Read endpoints are learner-scoped.
  expect(api.getPracticeSummary).toHaveBeenCalledWith("", undefined, "u_learner1");
  expect(api.getPracticeQueue).toHaveBeenCalledWith("", undefined, "u_learner1");
  expect(api.getPracticeAnalytics).toHaveBeenCalledWith("", 30, undefined, "u_learner1");
  // The write affordances of the learner's own page are absent.
  expect(screen.queryByRole("button", { name: "Start today's review" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Import questions" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Practice this page" })).not.toBeInTheDocument();
  // Per-material reading minutes appear in the breakdown panel.
  expect(screen.getByText("Materials in this period")).toBeVisible();
  expect(screen.getByText("rm_book")).toBeVisible();
  // Due questions render read-only, and a click opens the learner's entry.
  expect(screen.getByText("Which planet is largest?")).toBeVisible();
});

it("opens a due question's detail read-only", async () => {
  vi.mocked(api.getPracticeQuestion).mockResolvedValue(queueItem);
  render(<PracticeRoutePage />);
  fireEvent.click(await screen.findByText("Which planet is largest?"));
  await waitFor(() =>
    expect(api.getPracticeQuestion).toHaveBeenCalledWith(7, undefined, "u_learner1")
  );
  expect(await screen.findByText("Jupiter is the largest planet.")).toBeVisible();
  // No answer form or rating buttons exist anywhere in the guardian view.
  expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /again/i })).not.toBeInTheDocument();
});

it("surfaces a 403 for callers without view_reports", async () => {
  vi.mocked(guardianApi.getGuardianReport).mockRejectedValue(
    new Error("Guardian authorization required")
  );
  render(<PracticeRoutePage />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /Could not open this learner's practice/
  );
  expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
});
