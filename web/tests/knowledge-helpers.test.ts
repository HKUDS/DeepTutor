import test from "node:test";
import assert from "node:assert/strict";

import {
  kbCanReindex,
  providerUsesEmbeddingMetadata,
  resolveKnowledgeIndexFailure,
  taskFailureMessage,
  uploadPolicyForProvider,
  providerConnectionStatus,
  type KnowledgeBase,
} from "../lib/knowledge-helpers";

test("PageIndex providers do not expose embedding metadata", () => {
  assert.equal(providerUsesEmbeddingMetadata("pageindex"), false);
  assert.equal(providerUsesEmbeddingMetadata("pageindex-oss"), false);
  assert.equal(providerUsesEmbeddingMetadata("llamaindex"), true);
  assert.equal(providerUsesEmbeddingMetadata("graphrag"), true);
});

test("PageIndex OSS upload policy accepts PDF only", () => {
  const base = {
    extensions: [".pdf", ".pptx", ".txt"],
    accept: ".pdf,.pptx,.txt",
    max_file_size_bytes: 100,
  };
  assert.deepEqual(uploadPolicyForProvider(base, "pageindex-oss"), {
    extensions: [".pdf"],
    accept: ".pdf",
    max_file_size_bytes: 100,
  });
  assert.equal(uploadPolicyForProvider(base, "llamaindex"), base);
});

function kb(overrides: Partial<KnowledgeBase>): KnowledgeBase {
  return {
    name: "kb",
    status: "ready",
    statistics: { raw_documents: 1 },
    ...overrides,
  };
}

test("kbCanReindex allows failed knowledge bases with source files", () => {
  assert.equal(
    kbCanReindex(
      kb({
        status: "error",
        statistics: { raw_documents: 1, active_match: true },
      }),
    ),
    true,
  );
});

test("kbCanReindex keeps empty failed knowledge bases disabled", () => {
  assert.equal(
    kbCanReindex(
      kb({
        status: "error",
        statistics: { raw_documents: 0, active_match: false },
      }),
    ),
    false,
  );
});

test("kbCanReindex preserves mismatch and needs-reindex behavior", () => {
  assert.equal(
    kbCanReindex(kb({ statistics: { raw_documents: 1, needs_reindex: true } })),
    true,
  );
  assert.equal(
    kbCanReindex(kb({ statistics: { raw_documents: 1, active_match: false } })),
    true,
  );
  assert.equal(
    kbCanReindex(kb({ statistics: { raw_documents: 1, active_match: true } })),
    false,
  );
});

test("resolveKnowledgeIndexFailure preserves actionable backend metadata", () => {
  assert.deepEqual(
    resolveKnowledgeIndexFailure(
      kb({
        status: "error",
        progress: {
          stage: "error",
          error: "Choose a chat model that supports structured output.",
          error_code: "graphrag_model_incompatible",
          retryable: false,
        },
      }),
    ),
    {
      code: "graphrag_model_incompatible",
      message: "Choose a chat model that supports structured output.",
      retryable: false,
      requiresModelChange: true,
      settingsHref: "/settings/models",
    },
  );
});

test("resolveKnowledgeIndexFailure distinguishes configuration from transient failures", () => {
  const authentication = resolveKnowledgeIndexFailure(
    kb({
      status: "error",
      progress: {
        stage: "error",
        error_code: "graphrag_model_authentication_failed",
        retryable: false,
      },
    }),
  );
  const rateLimit = resolveKnowledgeIndexFailure(
    kb({
      status: "error",
      progress: {
        stage: "error",
        error_code: "graphrag_model_rate_limited",
        retryable: true,
      },
    }),
  );

  assert.equal(authentication?.requiresModelChange, true);
  assert.equal(authentication?.settingsHref, "/settings/models");
  assert.equal(rateLimit?.requiresModelChange, false);
  assert.equal(rateLimit?.settingsHref, undefined);
  assert.equal(rateLimit?.retryable, true);
});

test("resolveKnowledgeIndexFailure routes embedding configuration failures to embedding settings", () => {
  const endpointFailure = resolveKnowledgeIndexFailure(
    kb({
      status: "error",
      progress: {
        stage: "error",
        error_code: "graphrag_embedding_endpoint_failed",
        retryable: false,
      },
    }),
  );

  assert.equal(endpointFailure?.requiresModelChange, true);
  assert.equal(endpointFailure?.settingsHref, "/settings/embedding");
});

test("taskFailureMessage keeps trace details out of the primary error", () => {
  assert.equal(
    taskFailureMessage({
      detail: "GraphRAG preflight failed.",
      details: "Traceback: sensitive internal diagnostics",
    }),
    "GraphRAG preflight failed.",
  );
});

test("engine status follows the credential and install state", () => {
  // IMA holds one account credential pair, like PageIndex.
  assert.equal(
    providerConnectionStatus({
      id: "ima",
      configured: false,
      requires_api_key: true,
    }),
    "needs_key",
  );
  assert.equal(
    providerConnectionStatus({
      id: "ima",
      configured: true,
      requires_api_key: true,
    }),
    "ready",
  );
  assert.equal(
    providerConnectionStatus({ id: "llamaindex", configured: true }),
    "ready",
  );
  assert.equal(
    providerConnectionStatus({
      id: "pageindex",
      configured: false,
      requires_api_key: true,
    }),
    "needs_key",
  );
  assert.equal(
    providerConnectionStatus({ id: "graphrag", configured: false }),
    "unavailable",
  );
});
