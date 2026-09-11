import test from "node:test";
import assert from "node:assert/strict";

import { capabilityForPath } from "../lib/capability-routes";

// ── capabilityForPath ──────────────────────────────────────────────────

test("capabilityForPath maps LLM features to llm", () => {
  assert.equal(capabilityForPath("/chat"), "llm");
  assert.equal(capabilityForPath("/partners"), "llm");
  assert.equal(capabilityForPath("/co-writer"), "llm");
  assert.equal(capabilityForPath("/books"), "llm");
  assert.equal(capabilityForPath("/reading"), "llm");
  assert.equal(capabilityForPath("/mastery"), "llm"); // Mastery Path
});

test("capabilityForPath matches nested routes by prefix", () => {
  assert.equal(capabilityForPath("/chat/abc-123"), "llm");
  assert.equal(capabilityForPath("/partners/partner-1"), "llm");
  assert.equal(capabilityForPath("/mastery/book-1"), "llm");
  assert.equal(
    capabilityForPath("/reading/workspace-1/sessions/session-1"),
    "llm",
  );
});

test("capabilityForPath matches on a segment boundary, not a bare prefix", () => {
  // A sibling route must never be swallowed by a shorter gated prefix.
  assert.equal(capabilityForPath("/booket"), null);
  assert.equal(capabilityForPath("/homepage"), null);
  // The gated route itself and its children still match.
  assert.equal(capabilityForPath("/books"), "llm");
  assert.equal(capabilityForPath("/books/123"), "llm");
});

test("capabilityForPath returns null for ungated routes", () => {
  // Knowledge is ungated: embedding is shared admin infra, not per-user.
  assert.equal(capabilityForPath("/knowledge-bases"), null);
  assert.equal(capabilityForPath("/memory"), null);
  assert.equal(capabilityForPath("/space"), null);
  assert.equal(capabilityForPath("/settings"), null);
});
