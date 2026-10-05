import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import QuestionBankPicker, { type SelectedQuestionEntry } from "@/components/chat/QuestionBankPicker";
import { listNotebookEntries, type NotebookEntry } from "@/lib/notebook-api";
import { initI18n } from "@/i18n/init";

vi.mock("@/components/common/PickerShell", () => ({
  default: ({ open, children }: { open: boolean; children: ReactNode }) => open ? <div>{children}</div> : null,
}));
vi.mock("@/lib/notebook-api", () => ({
  listCategories: vi.fn(async () => []),
  listQuestionBankMaterials: vi.fn(async () => [
    { source: "immersive_reading", material_id: "A", material_title: "Material A", entry_count: 2, unresolved_count: 0 },
    { source: "immersive_reading", material_id: "B", material_title: "Material B", entry_count: 1, unresolved_count: 0 },
  ]),
  listNotebookEntries: vi.fn(),
}));
initI18n("en");
const entry = (id: number, material = "A"): NotebookEntry => ({
  id, session_id: "", session_title: "", turn_id: "", question_id: String(id), question: `Question ${id}`,
  question_type: "choice", options: {}, correct_answer: "", explanation: "", difficulty: "easy",
  user_answer: "", source: "immersive_reading", material_id: material, material_title: `Material ${material}`,
  section_id: "", section_title: "", score_trend: "new", is_correct: false, resolved: false,
  bookmarked: false, followup_session_id: "", created_at: 1, updated_at: 1,
});
const selected: SelectedQuestionEntry = { id: 99, question: "Previously selected", session_title: "", is_correct: false, difficulty: "easy" };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listNotebookEntries).mockImplementation(async (filter = {}) => {
    const rows = filter.material_id === "B" ? [entry(3, "B")] : [entry(1), entry(2)];
    return { items: rows, total: rows.length };
  });
});

it("keeps selections across material and text filters, then applies and restores them on reopen", async () => {
  const onApply = vi.fn();
  const onClose = vi.fn();
  const view = render(<QuestionBankPicker open initialSelected={[selected]} onApply={onApply} onClose={onClose} />);
  fireEvent.click(await screen.findByRole("button", { name: /Question 1/ }));
  fireEvent.change(screen.getByRole("combobox", { name: "Material" }), { target: { value: "B" } });
  fireEvent.click(await screen.findByRole("button", { name: /Question 3/ }));
  fireEvent.change(screen.getByPlaceholderText("Search questions by content"), { target: { value: "no-match" } });
  fireEvent.click(screen.getByRole("button", { name: "Use Selected Questions (3)" }));
  expect(onApply.mock.calls[0][0].map((row: SelectedQuestionEntry) => row.id)).toEqual([99, 1, 3]);
  expect(onClose).toHaveBeenCalledOnce();
  view.rerender(<QuestionBankPicker open={false} initialSelected={onApply.mock.calls[0][0]} onApply={onApply} onClose={onClose} />);
  view.rerender(<QuestionBankPicker open initialSelected={onApply.mock.calls[0][0]} onApply={onApply} onClose={onClose} />);
  fireEvent.change(screen.getByPlaceholderText("Search questions by content"), { target: { value: "" } });
  expect(await screen.findByRole("button", { name: /Question 3/ })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Clear" }));
  fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
  expect(onApply).toHaveBeenLastCalledWith([]);
});

it("loads later pages and selects only the visible search matches", async () => {
  const rows = Array.from({ length: 201 }, (_, i) => entry(i + 1));
  vi.mocked(listNotebookEntries).mockImplementation(async (filter = {}) => ({
    items: rows.slice(filter.offset ?? 0, (filter.offset ?? 0) + 200), total: rows.length,
  }));
  const onApply = vi.fn();
  render(<QuestionBankPicker open initialSelected={[]} onApply={onApply} onClose={vi.fn()} />);
  await screen.findByRole("button", { name: /Question 201/ });
  expect(listNotebookEntries).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 200, limit: 200 }));
  fireEvent.change(screen.getByPlaceholderText("Search questions by content"), { target: { value: "Question 201" } });
  fireEvent.click(screen.getByRole("button", { name: "Select all (1)" }));
  fireEvent.click(screen.getByRole("button", { name: "Use Selected Questions (1)" }));
  await waitFor(() => expect(onApply.mock.calls[0][0].map((row: SelectedQuestionEntry) => row.id)).toEqual([201]));
});
