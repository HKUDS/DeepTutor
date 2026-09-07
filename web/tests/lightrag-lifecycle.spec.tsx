import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import KbIndexVersionsSection from "@/components/knowledge/KbIndexVersionsSection";
import KnowledgeBaseDetail from "@/components/knowledge/KnowledgeBaseDetail";
import CreateKbModal from "@/components/knowledge/CreateKbModal";
import {
  DEFAULT_UPLOAD_POLICY,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";

vi.mock("@/components/knowledge/KbFilesTab", () => ({ default: () => null }));
vi.mock("@/features/knowledge/api/files", async (original) => ({
  ...(await original<typeof import("@/features/knowledge/api/files")>()),
  listKnowledgeBaseFiles: async () => [],
}));

const fixture = vi.hoisted(() => {
  const selection = {
    profile_id: "p",
    model_id: "model",
    reasoning_effort: "none",
  };
  return {
    t: (key: string) => key,
    selection,
    refresh: vi.fn(async () => {}),
    config: {
      version: 2,
      llm_profile_id: "",
      llm_model_id: "",
      top_k: 20,
      max_concurrent_files: 1,
      entity_extract_max_gleaning: 1,
      role_models: {
        base: selection,
        query: {
          mode: "model",
          selection: { profile_id: "p", model_id: "model" },
          max_async: 1,
          timeout: 60,
        },
        keyword: { mode: "inherit", max_async: 1, timeout: 60 },
        extract: { mode: "inherit", max_async: 1, timeout: 60 },
        vlm: { mode: "disabled", max_async: 1, timeout: 60 },
      },
    },
    preview: vi.fn(),
    create: vi.fn(async () => ({ task_id: null, files: [] })),
    options: [
      {
        ...selection,
        model_name: "Model one",
        model: "one",
        profile_name: "Provider",
        provider: "custom",
        is_active_default: true,
        supports_vision: true,
      },
    ],
  };
});
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: fixture.t }) }));
vi.mock("@/hooks/useLLMOptions", () => ({
  useLLMOptions: () => ({
    options: fixture.options,
    activeDefault: fixture.selection,
    loading: false,
    error: false,
    refresh: fixture.refresh,
  }),
}));
vi.mock("@/features/knowledge/api/engines", async (original) => ({
  ...(await original<typeof import("@/features/knowledge/api/engines")>()),
  getLightRagConfig: async () => structuredClone(fixture.config),
}));
vi.mock("@/features/knowledge/api/catalog", async (original) => ({
  ...(await original<typeof import("@/features/knowledge/api/catalog")>()),
  getReindexConfig: fixture.preview,
  createKnowledgeBase: fixture.create,
  listKnowledgeBases: async () => [],
  listRagProviders: async () => [],
  getKnowledgeUploadPolicy: async () => {
    throw new Error("use default upload policy");
  },
}));

const policy = {
  policy: "pinned",
  schema_version: 2,
  extract: {
    policy: "pinned",
    descriptor: {
      model: "Extract model",
      binding: "custom",
      reasoning_effort: "none",
    },
  },
  vlm: { mode: "disabled" as const },
};
const kb: KnowledgeBase = {
  name: "papers",
  status: "ready",
  metadata: { indexing_policy: policy },
  statistics: {
    rag_provider: "lightrag",
    raw_documents: 2,
    index_versions: [
      {
        version: "version-3",
        signature: "lightrag",
        provider: "lightrag",
        ready: true,
        embedding_model: "embedding-old",
        embedding_dim: 3,
        indexing_policy: policy,
      },
    ],
  },
};
const preview = (fingerprint: string, model = "embedding-current") => ({
  fingerprint,
  embedding: { model, dimension: 3 },
  indexing_policy: policy,
});

beforeEach(() => {
  fixture.preview.mockReset().mockResolvedValue(preview("first"));
  fixture.config.role_models.base = { ...fixture.selection };
});

it("shows version identifiers and a read-only rebuild confirmation, then requires reconfirmation after drift", async () => {
  const submit = vi
    .fn()
    .mockRejectedValueOnce(new Error("Default configuration changed"));
  render(<KbIndexVersionsSection kb={kb} onReindex={submit} />);
  expect(screen.getByText("version-3")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Re-index" }));
  const dialog = screen.getByRole("dialog");
  await within(dialog).findByText("embedding-current · 3d");
  expect(within(dialog).queryByRole("combobox")).not.toBeInTheDocument();
  fixture.preview.mockResolvedValue(preview("second", "embedding-new"));
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Confirm rebuild" }),
  );
  await within(dialog).findByText("embedding-new · 3d");
  expect(submit).toHaveBeenCalledExactlyOnceWith("first");
  expect(
    within(dialog).getByText("Default configuration changed"),
  ).toBeInTheDocument();
  submit.mockResolvedValue(undefined);
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Confirm rebuild" }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(submit).toHaveBeenLastCalledWith("second");
});

it("has no model or rebuild action for an empty knowledge base", () => {
  render(
    <KbIndexVersionsSection
      kb={{
        ...kb,
        statistics: {
          rag_provider: "lightrag",
          raw_documents: 0,
          index_versions: [],
        },
      }}
      onReindex={vi.fn()}
    />,
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByText("Index configuration")).not.toBeInTheDocument();
});

it("refreshes all four default roles on return from settings and creates without overrides", async () => {
  const create = vi.fn(async (_params: unknown) => {});
  render(
    <CreateKbModal
      isOpen
      onClose={vi.fn()}
      providers={[{ id: "lightrag", name: "LightRAG", description: "Graph" }]}
      uploadPolicy={DEFAULT_UPLOAD_POLICY}
      onCreate={create}
      onConnectLinkedFolder={vi.fn()}
      onConnectObsidian={vi.fn()}
      onConnectLightRagServer={vi.fn()}
      onConnectWeKnora={vi.fn()}
      onConnectMarginNote4={vi.fn()}
      onConnectIma={vi.fn()}
    />,
  );
  await screen.findByText("QUERY: Model one · Auto");
  expect(screen.getByText("KEYWORD: Model one · none")).toBeInTheDocument();
  expect(screen.getByText("EXTRACT: Model one · none")).toBeInTheDocument();
  expect(screen.getByText("VLM: Disabled")).toBeInTheDocument();
  expect(
    screen.queryByText("Customize indexing models"),
  ).not.toBeInTheDocument();
  fixture.config.role_models.base.reasoning_effort = "high";
  fireEvent(window, new Event("focus"));
  await screen.findByText("EXTRACT: Model one · high");
  const name = screen.getByPlaceholderText("e.g. project-papers");
  fireEvent.change(name, { target: { value: "empty" } });
  fireEvent.click(screen.getByRole("button", { name: "Create" }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  expect(create.mock.calls[0][0]).not.toHaveProperty("indexingLLM");
});

it.each(["header", "documents"])(
  "routes the %s LightRAG retry through refreshed rebuild confirmation",
  async (entry) => {
    const retry = vi.fn();
    const reindex = vi
      .fn()
      .mockRejectedValueOnce(new Error("Default configuration changed"));
    render(
      <KnowledgeBaseDetail
        kb={{ ...kb, status: "error" }}
        uploadPolicy={DEFAULT_UPLOAD_POLICY}
        history={[]}
        onCreate={vi.fn()}
        onUpload={vi.fn()}
        onReindex={reindex}
        onRetry={retry}
        onSetDefault={vi.fn()}
        onDelete={vi.fn()}
        onClearHistory={vi.fn()}
      />,
    );
    if (entry === "documents")
      fireEvent.click(screen.getByRole("button", { name: "Add documents" }));
    const buttons = screen.getAllByRole("button", { name: "Review rebuild" });
    fireEvent.click(buttons[entry === "header" ? 0 : buttons.length - 1]);
    expect(retry).not.toHaveBeenCalled();
    expect(reindex).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry indexing" }));
    const dialog = screen.getByRole("dialog");
    await within(dialog).findByText("embedding-current · 3d");
    fixture.preview.mockResolvedValue(preview("retry-new", "embedding-new"));
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm rebuild" }),
    );
    await within(dialog).findByText("embedding-new · 3d");
    expect(reindex).toHaveBeenCalledExactlyOnceWith("papers", "first");
    reindex.mockResolvedValue(undefined);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm rebuild" }),
    );
    await waitFor(() =>
      expect(reindex).toHaveBeenLastCalledWith("papers", "retry-new"),
    );
    expect(retry).not.toHaveBeenCalled();
  },
);
