import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { initI18n } from "@/i18n/init";
import BookStructureEditor from "@/app/(workspace)/learning/books/components/BookStructureEditor";
import BookEditReview from "@/app/(workspace)/learning/books/components/BookEditReview";
import type { BookDetail } from "@/lib/book-types";

const api = vi.hoisted(() => ({ previewEdit: vi.fn(), applyEdit: vi.fn(), listEdits: vi.fn() }));
vi.mock("@/lib/book-api", () => ({ bookApi: api }));
initI18n("en");
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const proposal = { id: "edit_one", status: "proposed", expected_revision: 1, diff: "+ New section content", edit: { title: "Limits" } };
const detail = { book: { id: "bk", revision: 1 }, spine: { chapters: [{ id: "ch_0", title: "Chapter", content_type: "theory" }] }, pages: [{ id: "pg_0", title: "Section", content_type: "theory" }] } as unknown as BookDetail;

it("manual editing previews without writing and applies only after explicit review", async () => {
  api.listEdits.mockResolvedValue({ edits: [] }); api.previewEdit.mockResolvedValue(proposal); api.applyEdit.mockResolvedValue({ ...proposal, status: "applied" });
  const changed = vi.fn();
  render(<BookStructureEditor detail={detail} onChanged={changed} onClose={() => {}} />);
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Limits" } });
  fireEvent.click(screen.getByText("Preview edit"));
  expect(await screen.findByText("+ New section content")).toBeVisible();
  expect(api.applyEdit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Apply reviewed edit"));
  await waitFor(() => expect(api.applyEdit).toHaveBeenCalledWith("bk", "edit_one", 1));
  expect(changed).toHaveBeenCalledOnce();
});

it("AI proposals from an earlier revision cannot be applied", async () => {
  api.listEdits.mockResolvedValue({ edits: [proposal] });
  render(<BookEditReview bookId="bk" pageId="pg_0" revision={2} onChanged={() => {}} />);
  const label = await screen.findByText("Limits");
  fireEvent.click(label);
  expect(screen.getByText("Apply reviewed edit")).toBeDisabled();
  expect(screen.getByText("Book changed; request a new proposal.")).toBeVisible();
  expect(api.applyEdit).not.toHaveBeenCalled();
});
