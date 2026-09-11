import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import path from "node:path";

import {
  createKnowledgeBase,
  reindexKnowledgeBase,
} from "../features/knowledge/api/client";
import {
  selectionFromLightRagDefault,
  selectionFromLLMOption,
} from "../components/knowledge/IndexingModelSelector";
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

test("create uses defaults and re-index sends only the confirmed fingerprint", async () => {
  const requests: Array<{ url: string; form: FormData }> = [];
  const restore = stubFetch(async (input, init) => {
    requests.push({ url: String(input), form: init?.body as FormData });
    return jsonResponse(200, { task_id: "task-1", noop: false });
  });
  try {
    await createKnowledgeBase({
      name: "papers",
      provider: "lightrag",
      files: [],
    });
    await reindexKnowledgeBase("papers", "confirmed-fingerprint");
  } finally {
    restore();
  }

  assert.equal(requests[0].url, "/api/knowledge-bases");
  assert.equal(requests[0].form.has("indexing_llm"), false);
  assert.equal(requests[1].url, "/api/knowledge-bases/papers/reindex");
  assert.equal(
    requests[1].form.get("config_fingerprint"),
    "confirmed-fingerprint",
  );
  assert.equal(requests[1].form.has("indexing_llm"), false);
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

test("model selectors are absent from create/rebuild and duplicate settings surfaces", () => {
  const root = process.cwd();
  for (const name of [
    "CreateKbModal",
    "KbIndexVersionsSection",
    "KbDocumentsSection",
  ]) {
    const source = readFileSync(
      path.join(root, `components/knowledge/${name}.tsx`),
      "utf8",
    );
    assert.doesNotMatch(source, /<LightRagIndexingSelector/);
  }
  const settings = readFileSync(
    path.join(root, "components/knowledge/KbSettingsSection.tsx"),
    "utf8",
  );
  assert.doesNotMatch(settings, /LightRagIndexingProvenance/);
});
