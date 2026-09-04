import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import path from "node:path";

import {
  createKnowledgeBase,
  reindexKnowledgeBase,
  updatePendingIndexingPolicy,
} from "../features/knowledge/api/client";
import {
  selectionFromLightRagDefault,
  selectionFromLLMOption,
} from "../components/knowledge/IndexingModelSelector";
import { selectionForLightRagModelDialog } from "../components/knowledge/KbIndexVersionsSection";
import {
  currentLightRagBuildCandidate,
  kbCanUploadDocuments,
  kbCanReindex,
  kbIsUploadable,
  lightRagVersionDisplayState,
  type KnowledgeBase,
} from "../lib/knowledge-helpers";

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

  assert.equal(requests[0].url, "/api/knowledge-bases");
  assert.deepEqual(
    JSON.parse(String(requests[0].form.get("indexing_llm"))),
    selection,
  );
  assert.equal(requests[1].url, "/api/knowledge-bases/papers/reindex");
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
  assert.equal(captured?.url, "/api/knowledge-bases/empty/indexing-policy");
  assert.equal(captured?.init?.method, "PUT");
  assert.deepEqual(JSON.parse(String(captured?.init?.body)), {
    profile_id: "p",
    model_id: "m",
  });
});

test("non-LightRAG re-index keeps the established bodyless request", async () => {
  let captured: RequestInit | undefined;
  const restore = stubFetch(async (_input, init) => {
    captured = init;
    return jsonResponse(200, { task_id: "task-2", noop: false });
  });
  try {
    await reindexKnowledgeBase("vectors");
  } finally {
    restore();
  }
  assert.equal(captured?.method, "POST");
  assert.equal(Object.hasOwn(captured ?? {}, "body"), false);
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

test("indexing defaults prefer the released LightRAG query model", () => {
  const active = {
    profile_id: "active-profile",
    model_id: "active-model",
    profile_name: "Active",
    model_name: "Active model",
    model: "active",
    provider: "openai",
    is_active_default: true,
  };
  const dedicated = {
    ...active,
    profile_id: "query-profile",
    model_id: "query-model",
    profile_name: "Query",
    model_name: "Query model",
    model: "query",
    is_active_default: false,
  };
  assert.deepEqual(
    selectionFromLightRagDefault(
      [active, dedicated],
      { llm_profile_id: "query-profile", llm_model_id: "query-model" },
      { profile_id: "active-profile", model_id: "active-model" },
    ),
    { profile_id: "query-profile", model_id: "query-model" },
  );
  assert.deepEqual(
    selectionFromLightRagDefault(
      [active, dedicated],
      { llm_profile_id: "", llm_model_id: "" },
      { profile_id: "active-profile", model_id: "active-model" },
    ),
    { profile_id: "active-profile", model_id: "active-model" },
  );
  assert.equal(
    selectionFromLightRagDefault(
      [active],
      { llm_profile_id: "missing", llm_model_id: "missing" },
      { profile_id: "active-profile", model_id: "active-model" },
    ),
    null,
  );
});

test("late catalog loading preserves an empty knowledge base's saved pending model", () => {
  const option = {
    profile_id: "saved-profile",
    model_id: "saved-model",
    profile_name: "Saved",
    model_name: "Saved model",
    model: "saved",
    provider: "openai",
    is_active_default: false,
  };
  assert.deepEqual(
    selectionForLightRagModelDialog(
      [option],
      { llm_profile_id: "current-profile", llm_model_id: "current-model" },
      null,
      {
        profile_id: "saved-profile",
        model_id: "saved-model",
        reasoning_effort: "none",
      },
      true,
    ),
    {
      profile_id: "saved-profile",
      model_id: "saved-model",
      reasoning_effort: "none",
    },
  );
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
  assert.equal(kbCanReindex({ ...kb, read_only: true }), false);
});

test("legacy LightRAG indexes stay queryable but are not uploadable", () => {
  const kb: KnowledgeBase = {
    name: "legacy-graph",
    status: "ready",
    metadata: { indexing_policy: { policy: "legacy_unpinned" } },
    statistics: { rag_provider: "lightrag", raw_documents: 1 },
  };
  assert.equal(kbIsUploadable(kb), false);
  assert.equal(kbCanUploadDocuments(kb, false), false);
  assert.equal(kbCanUploadDocuments({ ...kb, status: "error" }, false), false);
  assert.equal(kbCanReindex(kb), true);
});

test("ordinary error-state knowledge bases can replace failed files unless indexing is active", () => {
  const kb: KnowledgeBase = {
    name: "vectors",
    status: "error",
    statistics: { rag_provider: "llamaindex", raw_documents: 1 },
  };
  assert.equal(kbCanUploadDocuments(kb, false), true);
  assert.equal(kbCanUploadDocuments(kb, true), false);
});

test("LightRAG candidates distinguish active builds from failures", () => {
  const currentCandidate = {
    signature: "version-3",
    ready: false,
  };
  const olderFailure = {
    signature: "version-2",
    provider: "lightrag",
    ready: false,
    failure_summary: "paper.pdf: parse failed",
  };
  assert.equal(
    currentLightRagBuildCandidate([currentCandidate, olderFailure], true),
    currentCandidate,
  );
  assert.equal(currentLightRagBuildCandidate([olderFailure], false), undefined);
  assert.equal(
    lightRagVersionDisplayState(currentCandidate, {
      published: false,
      rebuildActive: true,
      kbError: false,
      legacy: false,
    }),
    "building",
  );
  assert.equal(
    lightRagVersionDisplayState(olderFailure, {
      published: false,
      rebuildActive: false,
      kbError: false,
      legacy: false,
    }),
    "failed",
  );
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
  const detailSource = readFileSync(
    path.join(root, "components/knowledge/KnowledgeBaseDetail.tsx"),
    "utf8",
  );
  const provenanceSource = readFileSync(
    path.join(root, "components/knowledge/LightRagIndexingProvenance.tsx"),
    "utf8",
  );
  assert.match(createSource, /provider === ['"]lightrag['"] \? \(/);
  assert.match(createSource, /indexingLLM:\s*provider === ['"]lightrag['"]/);
  assert.doesNotMatch(uploadSource, /IndexingModelSelector/);
  assert.match(uploadSource, /LightRagIndexingProvenance/);
  assert.match(provenanceSource, /compact && \(/);
  assert.match(
    provenanceSource,
    /modelLabel \|\| t\(['"]Unverified historical indexing model['"]\)/,
  );
  assert.match(
    provenanceSource,
    /t\(['"]Reasoning effort['"]\).*effort \|\| t\(['"]Model default['"]\)/s,
  );
  assert.match(
    detailSource,
    /status === ['"]error['"] && kbProvider\(kb\) !== ['"]lightrag['"]/,
  );
});
