import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import CoWriterWorkspace from "@/features/co-writer/components/CoWriterWorkspace";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/components/common/MarkdownRenderer", () => ({ default: () => null }));
vi.mock("@/features/knowledge/api/catalog", () => ({
  listKnowledgeBases: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/lib/co-writer-api", () => ({
  getCoWriterDocument: vi.fn().mockResolvedValue({
    id: "document-1",
    title: "Existing document",
    content: "Existing draft content",
    updated_at: 1,
  }),
  updateCoWriterDocument: vi.fn().mockResolvedValue({}),
  exportCoWriterDocx: vi.fn(),
}));
vi.mock("@/lib/notebook-api", () => ({
  listNotebooks: vi.fn().mockResolvedValue([{ id: "notebook-1", name: "My notebook" }]),
  createNotebook: vi.fn(),
}));

it("opens and closes the dynamically loaded notebook picker without changing the draft", async () => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  try {
    render(<CoWriterWorkspace docId="document-1" />);
    expect(await screen.findByDisplayValue("Existing draft content")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save to Notebook" }));
    const dialog = await screen.findByRole("dialog", { name: "Save to Notebook" });
    expect(await within(dialog).findByText("My notebook")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByDisplayValue("Existing draft content")).toBeInTheDocument();
  } finally {
    vi.unstubAllGlobals();
  }
});
