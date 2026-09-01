import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import path from "node:path";

import {
  createKnowledgeBase,
  reindexKnowledgeBase,
  updatePendingIndexingPolicy,
} from "../lib/knowledge-api";
import { selectionFromLLMOption } from "../components/knowledge/IndexingModelSelector";
import { kbCanReindex, type KnowledgeBase } from "../lib/knowledge-helpers";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(
  handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return () => {
    globalThis.fetch = original;
  };
}

test("create and re-index send the exact pinned selection and preserve none", async () => {
  const requests: Array<{ url: string; form: FormData }> = [];
  const restore = stubFetch(async (input, init) => {
    requests.push({ url: String(input), form: init?.body as FormData });
    return jsonResponse(200, { task_id: "task-1", noop: false });
  });
  const selection = {
    profile_id: "profile-1",
    model_id: "model-1",
    reasoning_effort: "none",
  };
  try {
    await createKnowledgeBase({
      name: "papers",
      provider: "lightrag",
      files: [],
      indexingLLM: selection,
    });
    await reindexKnowledgeBase("papers", selection);
  } finally {
    restore();
  }

  assert.equal(requests[0].url, "/api/v1/knowledge/create");
  assert.deepEqual(
    JSON.parse(String(requests[0].form.get("indexing_llm"))),
    selection,
  );
  assert.equal(requests[1].url, "/api/v1/knowledge/papers/reindex");
  assert.deepEqual(
    JSON.parse(String(requests[1].form.get("indexing_llm"))),
    selection,
  );
});

test("pending-policy update is JSON-only and creates no indexing request", async () => {
  let captured: { url: string; init?: RequestInit } | undefined;
  const restore = stubFetch(async (input, init) => {
    captured = { url: String(input), init };
    return jsonResponse(200, { indexing_policy: { policy: "pending_pinned" } });
  });
  try {
    await updatePendingIndexingPolicy("empty", {
      profile_id: "p",
      model_id: "m",
    });
  } finally {
    restore();
  }
  assert.equal(captured?.url, "/api/v1/knowledge/empty/indexing-policy");
  assert.equal(captured?.init?.method, "PUT");
  assert.deepEqual(JSON.parse(String(captured?.init?.body)), {
    profile_id: "p",
    model_id: "m",
  });
});

test("model defaults are inherited while an explicit none remains serialized", () => {
  const option = {
    profile_id: "p",
    model_id: "m",
    profile_name: "OpenAI",
    model_name: "GPT",
    model: "gpt-5",
    provider: "openai",
    is_active_default: true,
    reasoning_effort: "high",
  };
  assert.deepEqual(selectionFromLLMOption(option), {
    profile_id: "p",
    model_id: "m",
  });
  assert.deepEqual(selectionFromLLMOption(option, "none"), {
    profile_id: "p",
    model_id: "m",
    reasoning_effort: "none",
  });
});

test("healthy LightRAG knowledge bases retain a full re-index entry", () => {
  const kb: KnowledgeBase = {
    name: "graph",
    status: "ready",
    statistics: {
      raw_documents: 2,
      rag_provider: "lightrag",
      active_match: true,
    },
  };
  assert.equal(kbCanReindex(kb), true);
});

test("model controls are scoped to built-in LightRAG create/rebuild surfaces", () => {
  const root = path.resolve(process.cwd());
  const createSource = readFileSync(
    path.join(root, "components/knowledge/CreateKbModal.tsx"),
    "utf8",
  );
  const uploadSource = readFileSync(
    path.join(root, "components/knowledge/KbDocumentsSection.tsx"),
    "utf8",
  );
  assert.match(createSource, /provider === "lightrag" \? \(/);
  assert.match(createSource, /indexingLLM:\s*provider === "lightrag"/);
  assert.doesNotMatch(uploadSource, /IndexingModelSelector/);
  assert.match(uploadSource, /LightRagIndexingProvenance/);
});
