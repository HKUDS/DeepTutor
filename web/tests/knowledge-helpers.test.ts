import test from "node:test";
import assert from "node:assert/strict";

import {
  kbCanReindex,
  providerConnectionStatus,
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

test("IMA is connected per knowledge base instead of globally ready", () => {
  assert.equal(providerConnectionStatus({ id: "ima", configured: true }), "per_kb");
  assert.equal(providerConnectionStatus({ id: "llamaindex", configured: true }), "ready");
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
