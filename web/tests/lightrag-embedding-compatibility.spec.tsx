import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import KnowledgeBaseDetail from "@/components/knowledge/KnowledgeBaseDetail";
import KbIndexVersionsSection from "@/components/knowledge/KbIndexVersionsSection";
import KnowledgeHome from "@/components/knowledge/KnowledgeHome";
import {
  DEFAULT_UPLOAD_POLICY,
  kbCanUploadDocuments,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";

const fixture = vi.hoisted(() => ({
  t: (key: string) => key,
  refresh: vi.fn(async () => {}),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: fixture.t }) }));
vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("@/features/knowledge/api/engines", async (original) => ({
  ...(await original<typeof import("@/features/knowledge/api/engines")>()),
  getLightRagConfig: async () => ({ llm_profile_id: "", llm_model_id: "" }),
}));
vi.mock("@/hooks/useLLMOptions", () => ({
  useLLMOptions: () => ({
    options: [],
    activeDefault: null,
    loading: false,
    error: false,
    refresh: fixture.refresh,
  }),
}));
vi.mock("@/features/knowledge/api/files", async (original) => ({
  ...(await original<typeof import("@/features/knowledge/api/files")>()),
  listKnowledgeBaseFiles: async () => [
    { name: "paper.txt", type: "file", size: 12, mime_type: "text/plain" },
  ],
}));

const kb: KnowledgeBase = {
  name: "papers",
  status: "ready",
  metadata: {
    indexing_policy: { policy: "pinned" },
    embedding_mismatch: true,
    indexed_embedding_model: "original-model",
    indexed_embedding_dim: 3,
    current_embedding_model: "current-model",
    current_embedding_dim: 3,
  },
  statistics: {
    rag_provider: "lightrag",
    raw_documents: 1,
    index_versions: [{ version: "version-1", provider: "lightrag", ready: true }],
  },
};

it("omits mismatch warnings from list cards", () => {
  render(
    <KnowledgeHome
      kbs={[kb]}
      providers={[]}
      onOpenKb={vi.fn()}
      onOpenEngine={vi.fn()}
      onOpenSource={vi.fn()}
      onCreate={vi.fn()}
      activeSection="knowledge-bases"
      onSectionChange={vi.fn()}
    />,
  );
  expect(screen.queryByText(/Restore the original configuration/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Index embedding.*original-model/)).not.toBeInTheDocument();
});

it("shows detail guidance while files and downloads remain accessible", async () => {
  render(
    <KnowledgeBaseDetail
      kb={kb}
      uploadPolicy={DEFAULT_UPLOAD_POLICY}
      history={[]}
      onCreate={vi.fn()}
      onUpload={vi.fn()}
      onReindex={vi.fn()}
      onUpdatePendingIndexingPolicy={vi.fn()}
      onRetry={vi.fn()}
      onSetDefault={vi.fn()}
      onDelete={vi.fn()}
      onClearHistory={vi.fn()}
    />,
  );
  expect(screen.getByText(/Restore the original configuration/)).toBeInTheDocument();
  expect(screen.getByText(/Index embedding.*original-model/)).toBeInTheDocument();
  expect(screen.getByText(/Current embedding.*current-model/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Files" }));
  fireEvent.click(await screen.findByText("paper.txt"));
  expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
    "href",
    expect.stringContaining("/knowledge-bases/papers/files/paper.txt"),
  );
});

it("keeps version guidance visible alongside a failed rebuild", async () => {
  await act(async () => { render(
    <KbIndexVersionsSection
      kb={{ ...kb, status: "error" }}
      onReindex={vi.fn()}
      onUpdatePendingIndexingPolicy={vi.fn()}
    />,
  ); });
  expect(screen.getByText(/Restore the original configuration/)).toBeInTheDocument();
  expect(screen.getByText(/Index embedding.*original-model/)).toBeInTheDocument();
  expect(screen.getByText(/Current embedding.*current-model/)).toBeInTheDocument();
});

it.each(["ready", "error"])("blocks incompatible appends in %s state and restores them", (status) => {
  expect(kbCanUploadDocuments({ ...kb, status }, false)).toBe(false);
  expect(
    kbCanUploadDocuments(
      { ...kb, status, metadata: { ...kb.metadata, embedding_mismatch: false } },
      false,
    ),
  ).toBe(true);
});
