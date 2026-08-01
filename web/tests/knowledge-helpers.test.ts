import test from "node:test";
import assert from "node:assert/strict";

import {
  kbCanReindex,
  resolveKnowledgeIndexFailure,
  taskFailureMessage,
  type KnowledgeBase,
} from "../lib/knowledge-helpers";

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
  assert.equal(rateLimit?.requiresModelChange, false);
  assert.equal(rateLimit?.retryable, true);
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
