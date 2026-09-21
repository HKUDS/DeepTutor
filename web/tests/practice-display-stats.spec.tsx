import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import QuestionCard from "@/components/space/question-bank/QuestionCard";
import { PracticeInsights } from "@/components/learning/practice/PracticeInsights";
import { initI18n } from "@/i18n/init";
import type { NotebookEntry } from "@/lib/notebook-api";
import * as api from "@/lib/practice-api";
import { practiceMarkdown } from "@/lib/practice-content";

let query = "course=course-a&view=mistakes";
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(query),
  useRouter: () => ({ replace }),
}));
vi.mock("@/lib/practice-api", async original => ({
  ...(await original<typeof api>()),
  getPracticeAnalytics: vi.fn(),
}));
vi.mock("next/dynamic", () => ({
  default:
    () =>
    ({ content }: { content: string }) => <div>{content}</div>,
}));
initI18n("en");
const report: api.PracticeAnalytics = {
  timezone: "UTC",
  days: 7,
  start_date: "2026-09-18",
  end_date: "2026-09-19",
  updated_at: 100,
  totals: { questions: 3, mistakes: 1, reviews: 2 },
  daily: [
    { date: "2026-09-18", questions: 3, mistakes: 0, reviews: 0 },
    { date: "2026-09-19", questions: 0, mistakes: 1, reviews: 2 },
  ],
  sources: [
    { source: "mastery_path", questions: 2, mistakes: 1, reviews: 2 },
    { source: "book", questions: 1, mistakes: 0, reviews: 0 },
  ],
};
beforeEach(() => {
  vi.clearAllMocks();
  query = "course=course-a&view=mistakes";
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    }
  );
  vi.mocked(api.getPracticeAnalytics).mockResolvedValue(report);
});

it("separates legacy code fences without changing code or inline literals", () => {
  expect(practiceMarkdown("题干？```python\nx = '<State>'\n```")).toBe(
    "题干？\n\n```python\nx = '<State>'\n```"
  );
  expect(practiceMarkdown("Read `state['messages']`.\n\n```python\nx=1\n```")).toBe(
    "Read `state['messages']`.\n\n```python\nx=1\n```"
  );
});

it("keeps the complete stem and choices visible while hiding answer evidence", async () => {
  const entry = {
    id: 1,
    question: "What does node_2 read?",
    question_type: "choice",
    options: { A: "The previous messages", B: "An empty list" },
    correct_answer: "A",
    user_answer: "B",
    result: "incorrect",
    source: "mastery_path",
    explanation: "Fields are merged.",
    categories: [],
    session_id: "session-a",
    material_id: "path-a",
    created_at: 100,
    updated_at: 100,
  } as unknown as NotebookEntry;
  render(
    <ul>
      <QuestionCard
        entry={entry}
        collapseAnswers
        categories={[]}
        selected={false}
        disabled={false}
        onToggleSelected={vi.fn()}
        onToggleBookmark={vi.fn()}
        onToggleResolved={vi.fn()}
        onDelete={vi.fn()}
        onFile={vi.fn()}
        onUnfile={vi.fn()}
        onCreateAndFile={vi.fn()}
      />
    </ul>
  );
  expect(screen.getByTestId("question-stem")).toHaveTextContent("What does node_2 read?");
  expect(screen.getByText("The previous messages").closest("details")).toBeNull();
  expect(screen.queryByText(/Your pick/)).not.toBeInTheDocument();
  expect(screen.getByText("Fields are merged.")).not.toBeVisible();
  expect(screen.getByRole("link", { name: "Original Session" })).toHaveAttribute(
    "href",
    "/learning/mastery/path-a/sessions/session-a"
  );
  await userEvent.click(screen.getByText("Answer and explanation"));
  await waitFor(() => expect(screen.getByText(/Your pick/)).toBeVisible());
  expect(screen.getByText("Fields are merged.")).toBeVisible();
});

it("switches metrics and charts without losing course scope and exposes exact daily values", async () => {
  const { rerender } = render(<PracticeInsights courseId="course-a" revision={0} />);
  await screen.findByText("Mastery Path");
  fireEvent.click(screen.getByRole("button", { name: /New mistakes/ }));
  expect(replace.mock.calls.at(-1)?.[0]).toContain(
    "course=course-a&view=mistakes&stats_metric=mistakes"
  );
  query += "&stats_metric=mistakes";
  rerender(<PracticeInsights courseId="course-a" revision={0} />);
  expect(screen.queryByText("Book")).not.toBeInTheDocument();
  expect(screen.getByText("100%")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Bar chart" }));
  expect(replace.mock.calls.at(-1)?.[0]).toContain("stats_chart=bars");
  await userEvent.click(screen.getByText("View daily data"));
  expect(within(screen.getByRole("table")).getByText("2026-09-18")).toBeVisible();
  expect(api.getPracticeAnalytics).toHaveBeenCalledWith("course-a", 30, undefined);
});

it("shows an error and permits retry instead of presenting failed data as zero", async () => {
  vi.mocked(api.getPracticeAnalytics).mockRejectedValueOnce(new Error("Offline"));
  render(<PracticeInsights courseId="course-a" revision={0} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByText("Mastery Path");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
