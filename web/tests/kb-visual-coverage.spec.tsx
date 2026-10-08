import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KbVisualCoverage from "@/components/knowledge/KbVisualCoverage";
import { apiFetch } from "@/shared/api/client";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/shared/api/client", () => ({ apiFetch: vi.fn(), apiUrl: (path: string) => path }));
vi.mock("@/features/knowledge/api/files", () => ({ knowledgeBaseFilePath: (kb: string, name: string) => `/api/knowledge-bases/${kb}/files/${name}` }));

const report = { documents: [{ source_path: "book.pdf", retained_count: 100, page_fallback: true, issues: [{ reason: "referenced_image_not_retained", status: "unverified", page: 88 }] }],
  assets: [{ asset_id: "known", caption: "Figure 1.99", page_number: 100, source_path: "book.pdf" }], total_assets: 100, offset: 0, limit: 20 };
beforeEach(() => vi.clearAllMocks());
describe("Inspectable source visual coverage", () => {
  it("shows honest limits, missing locations, source links and pages beyond 64", async () => {
    vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify(report)));
    render(<KbVisualCoverage kbName="kb" sourcePath="book.pdf" revision={0} />);
    fireEvent.click(screen.getByText("Source visual coverage"));
    await screen.findByText("Retained source figures", { exact: false });
    expect(screen.getByText("Extracted figures do not prove complete visual coverage. Inspect the original page when labels, vectors or tables are missing.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Page 88:" })).toHaveAttribute("href", "/api/knowledge-bases/kb/files/book.pdf#page=88");
    expect(screen.getByRole("link", { name: "Figure 1.99 (Page 100)" })).toHaveAttribute("href", "/api/knowledge-bases/kb/visual-assets/known");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.at(-1)?.[0]).toContain("offset=20"));
  });
  it("displays unreadable or missing source states rather than permanent loading", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response("{}", { status: 409 })).mockResolvedValueOnce(new Response(JSON.stringify({ documents: [], assets: [], total_assets: 0 })));
    const view = render(<KbVisualCoverage kbName="kb" sourcePath="book.pdf" revision={0} />);
    fireEvent.click(screen.getByText("Source visual coverage"));
    await screen.findByText("Could not read visual coverage. Open the original document to inspect the source.");
    view.rerender(<KbVisualCoverage kbName="kb" sourcePath="book.pdf" revision={1} />);
    await screen.findByText("Source document is unavailable. Refresh the file list.");
  });
});
