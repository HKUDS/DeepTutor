import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import CoWriterWorkspace from "@/features/co-writer/components/CoWriterWorkspace";
import { loadDraft, saveDraft } from "@/features/co-writer/storage/drafts";
import { getCoWriterDocument } from "@/lib/co-writer-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("@/hooks/useLLMOptions", () => ({
  useLLMOptions: () => ({ options: [], activeDefault: null, loading: false, error: false, refresh: vi.fn() }),
}));
vi.mock("@/features/knowledge/api/catalog", () => ({ listKnowledgeBases: async () => [] }));
vi.mock("@/lib/co-writer-api", () => ({
  getCoWriterDocument: vi.fn(async (docId: string) => ({
    id: docId, title: docId, content: `${docId} server content`, created_at: 1, updated_at: 1,
  })),
  updateCoWriterDocument: vi.fn(),
  exportCoWriterDocx: vi.fn(),
}));

it("keeps a newly selected document's content and local buffer isolated", async () => {
  localStorage.clear();
  const view = render(<CoWriterWorkspace docId="first" />);
  await waitFor(() => expect(screen.getByPlaceholderText("Start writing in Markdown...")).toHaveValue("first server content"));
  view.rerender(<CoWriterWorkspace docId="second" />);
  await waitFor(() => expect(screen.getByPlaceholderText("Start writing in Markdown...")).toHaveValue("second server content"));
  expect(loadDraft(localStorage, "second")?.content).toBe("second server content");
});

it("preserves both documents' independent unsaved drafts", async () => {
  localStorage.clear();
  saveDraft(localStorage, "second", "second unsaved draft", 4);
  const view = render(<CoWriterWorkspace docId="first" />);
  const editor = await screen.findByPlaceholderText("Start writing in Markdown...");
  fireEvent.change(editor, { target: { value: "first unsaved draft" } });
  view.rerender(<CoWriterWorkspace docId="second" />);
  await waitFor(() => expect(screen.getByPlaceholderText("Start writing in Markdown...")).toHaveValue("second unsaved draft"));
  expect(loadDraft(localStorage, "first")?.content).toBe("first unsaved draft");
  expect(loadDraft(localStorage, "second")?.content).toBe("second unsaved draft");
});

it("ignores a previous document's delayed load after navigation", async () => {
  localStorage.clear();
  let resolveFirst!: (document: Awaited<ReturnType<typeof getCoWriterDocument>>) => void;
  vi.mocked(getCoWriterDocument).mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
  const view = render(<CoWriterWorkspace docId="first" />);
  view.rerender(<CoWriterWorkspace docId="second" />);
  await waitFor(() => expect(screen.getByPlaceholderText("Start writing in Markdown...")).toHaveValue("second server content"));
  await act(async () => {
    resolveFirst({ id: "first", title: "first", content: "late first content", created_at: 1, updated_at: 1 });
  });
  expect(screen.getByPlaceholderText("Start writing in Markdown...")).toHaveValue("second server content");
});
