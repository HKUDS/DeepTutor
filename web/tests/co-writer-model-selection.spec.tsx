import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import CoWriterWorkspace from "@/features/co-writer/components/CoWriterWorkspace";
import { apiFetch } from "@/lib/api";

const fetcher = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => path,
  apiFetch: fetcher,
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
  listNotebooks: vi.fn().mockResolvedValue([]),
  createNotebook: vi.fn(),
}));
vi.mock("@/hooks/useLLMOptions", () => ({
  useLLMOptions: () => ({
    options: [
      {
        profile_id: "profile-1",
        model_id: "default-model",
        profile_name: "Primary profile",
        model_name: "Default model",
        model: "default-model",
        provider: "openai",
        is_active_default: true,
      },
      {
        profile_id: "profile-2",
        model_id: "writing-model",
        profile_name: "Writing profile",
        model_name: "Writing model",
        model: "writing-model",
        provider: "openrouter",
        is_active_default: false,
      },
    ],
    activeDefault: { profile_id: "profile-1", model_id: "default-model" },
    loading: false,
    error: false,
    refresh: vi.fn(),
  }),
}));

it("sends the selected model with a full-draft edit", async () => {
  fetcher.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ edited_text: "Edited draft", operation_id: "operation-1" }),
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  const user = userEvent.setup();

  try {
    render(<CoWriterWorkspace docId="document-1" />);
    expect(await screen.findByDisplayValue("Existing draft content")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Full Draft" }));
    await user.click(await screen.findByRole("button", { name: "Select model" }));
    await user.click(
      screen.getByRole("button", { name: "Writing model | Writing profile" }),
    );
    await user.type(
      screen.getByPlaceholderText("Describe how you want the text edited..."),
      "Tighten this draft",
    );
    await user.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const [endpoint, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(endpoint).toBe("/api/documents/actions/edit");
    expect(JSON.parse(String(init.body))).toEqual({
      text: "Existing draft content",
      instruction: "Tighten this draft",
      action: "rewrite",
      source: null,
      kb_name: null,
      llm_selection: { profile_id: "profile-2", model_id: "writing-model" },
    });
  } finally {
    vi.unstubAllGlobals();
  }
});
