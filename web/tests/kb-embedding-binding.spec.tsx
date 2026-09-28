import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useEmbeddingModels } from "@/hooks/useEmbeddingModels";
import KbIndexVersionsSection from "@/components/knowledge/KbIndexVersionsSection";
import EmbeddingModelUsage from "@/components/settings/EmbeddingModelUsage";
import {
  createKnowledgeBase,
  reindexKnowledgeBase,
} from "@/features/knowledge/api/client";
import type { KnowledgeBase } from "@/lib/knowledge-helpers";

const fixtures = vi.hoisted(() => ({
  models: vi.fn(),
  usage: vi.fn(),
  fetch: vi.fn(),
  lightRagConfig: vi.fn(),
  llmOptions: vi.fn(),
  t: (key: string) => key,
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: fixtures.t }) }));
vi.mock("@/features/knowledge/api/engines", () => ({
  getEngineModelOptions: fixtures.models,
  getEmbeddingUsage: fixtures.usage,
  getLightRagConfig: fixtures.lightRagConfig,
}));
vi.mock("@/hooks/useLLMOptions", () => ({
  useLLMOptions: fixtures.llmOptions,
}));
vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => fixtures.fetch(...args),
  apiUrl: (url: string) => url,
}));

const a = { profile_id: "provider", model_id: "a" };
const b = { profile_id: "provider", model_id: "b" };
beforeEach(() => {
  fixtures.models.mockReset().mockResolvedValue({
    embedding: {
      active: b,
      options: [a, b].map((selection) => ({
        ...selection,
        label: `Model ${selection.model_id}`,
        model: selection.model_id,
        profile_name: "Provider",
        detail: "2d",
      })),
    },
  });
  fixtures.fetch
    .mockReset()
    .mockResolvedValue({
      ok: true,
      json: async () => ({
        task_id: "task",
        fingerprint: "confirmed",
        embedding: { model: "b", dimension: 2 },
        indexing_policy: { policy: "defaults" },
      }),
    });
  fixtures.usage.mockReset();
  fixtures.lightRagConfig.mockReset().mockResolvedValue({});
  fixtures.llmOptions.mockReset().mockReturnValue({
    options: [],
    loading: false,
    error: null,
  });
});
afterEach(cleanup);

it("selects a KB's original model even when the global default changed", async () => {
  const { result } = renderHook(() => useEmbeddingModels(a));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.selection).toMatchObject(a);
});

it("does not silently select the default after a bound model was deleted", async () => {
  const { result } = renderHook(() =>
    useEmbeddingModels({ ...a, model_id: "deleted" }),
  );
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.selection).toBeNull();
});

it("lets a healthy KB explicitly re-index with another configured embedding model", async () => {
  const onReindex = vi.fn().mockResolvedValue(undefined);
  const kb = {
    name: "notes",
    status: "ready",
    metadata: { embedding_selection: a, embedding_status: "ready" },
    statistics: {
      raw_documents: 2,
      rag_provider: "llamaindex",
      active_match: true,
      index_versions: [],
    },
  } as unknown as KnowledgeBase;
  render(<KbIndexVersionsSection kb={kb} onReindex={onReindex} />);
  fireEvent.click(screen.getByRole("button", { name: "Re-index" }));
  await waitFor(() =>
    expect(
      screen.getByRole("combobox", { name: "Embedding model" }),
    ).toHaveValue(JSON.stringify([a.profile_id, a.model_id])),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Embedding model" }), {
    target: { value: JSON.stringify([b.profile_id, b.model_id]) },
  });
  fireEvent.click(screen.getByRole("button", { name: "Start full re-index" }));
  await waitFor(() =>
    expect(onReindex).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining(b),
    ),
  );
});

it("lists affected knowledge bases and explains that deletion preserves their data", async () => {
  fixtures.usage.mockResolvedValue([
    { ...a, name: "Physics", workspace_name: "Study" },
    { ...b, name: "Hidden other model", workspace_name: "" },
  ]);
  render(<EmbeddingModelUsage profileId={a.profile_id} modelId={a.model_id} />);
  await screen.findByText("Physics · Study");
  expect(screen.queryByText("Hidden other model")).toBeNull();
  expect(screen.getByText(/Deleting this model is allowed/)).toBeVisible();
});

it("lets an empty LightRAG KB replace a deleted embedding model before its first upload", async () => {
  const onReindex = vi.fn().mockResolvedValue(undefined);
  const llm = { profile_id: "chat", model_id: "chat-model" };
  fixtures.llmOptions.mockReturnValue({
    options: [
      {
        ...llm,
        model: "chat",
        model_name: "Chat",
        profile_name: "Provider",
        provider: "openai",
      },
    ],
    activeDefault: llm,
    loading: false,
    error: null,
  });
  const kb = {
    name: "empty",
    status: "ready",
    metadata: {
      embedding_selection: { ...a, model_id: "deleted" },
      embedding_status: "missing",
    },
    statistics: {
      raw_documents: 0,
      rag_provider: "lightrag",
      index_versions: [],
    },
  } as unknown as KnowledgeBase;
  render(<KbIndexVersionsSection kb={kb} onReindex={onReindex} />);
  fireEvent.click(screen.getByRole("button", { name: "Change model" }));
  const picker = await screen.findByRole("combobox", {
    name: "Embedding model",
  });
  await waitFor(() => expect(picker).toBeEnabled());
  expect(screen.getByRole("button", { name: "Save model" })).toBeDisabled();
  fireEvent.change(picker, {
    target: { value: JSON.stringify([b.profile_id, b.model_id]) },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save model" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save model" }));
  await waitFor(() => expect(onReindex).toHaveBeenCalledWith("confirmed", b));
});

it("sends model IDs on create and re-index without activating a global model", async () => {
  await createKnowledgeBase({
    name: "notes",
    provider: "llamaindex",
    files: [],
    embeddingModel: a,
  });
  await reindexKnowledgeBase("notes", undefined, b);
  expect(fixtures.fetch).toHaveBeenCalledTimes(2);
  const [create, reindex] = fixtures.fetch.mock.calls;
  expect(JSON.parse(create[1].body.get("embedding_model"))).toEqual(a);
  expect(JSON.parse(reindex[1].body.get("embedding_model"))).toEqual(b);
  expect(reindex[0]).toBe("/api/knowledge-bases/notes/reindex");
});

it("recovers usage after retry and clears the previous model's error", async () => {
  fixtures.usage
    .mockRejectedValueOnce(new Error("unavailable"))
    .mockResolvedValue([]);
  const view = render(<EmbeddingModelUsage profileId="p" modelId="a" />);
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByText("No knowledge bases use this model.");
  expect(screen.queryByRole("alert")).toBeNull();
  fixtures.usage.mockRejectedValueOnce(new Error("unavailable"));
  view.rerender(<EmbeddingModelUsage profileId="p" modelId="b" />);
  await screen.findByRole("alert");
  view.rerender(<EmbeddingModelUsage profileId="p" modelId="c" />);
  await screen.findByText("No knowledge bases use this model.");
  expect(screen.queryByRole("alert")).toBeNull();
});
