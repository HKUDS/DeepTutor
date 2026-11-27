import assert from "node:assert/strict";
import test from "node:test";

import { extractCreationDraft } from "@/lib/creation-draft";
import type { StreamEvent } from "@/features/chat/model/protocol";

function toolResult(creationDraft: Record<string, unknown>): StreamEvent {
  return {
    type: "tool_result",
    source: "chat",
    stage: "responding",
    seq: 1,
    content: "ok",
    metadata: { tool_metadata: { creation_draft: creationDraft } },
    timestamp: Date.now(),
  };
}

const BASE = {
  draft_id: "a".repeat(32),
  owner_id: "u-alice",
  kind: "skill",
  session_id: "s-1",
  name: "ada-helper",
  description: "Helps with Ada proofs",
  content: "# Ada helper\nBe rigorous.",
  status: "pending",
  version: 1,
};

test("extractCreationDraft reads a valid draft card payload, defaulting missing optional fields", () => {
  const draft = extractCreationDraft([toolResult(BASE)]);
  assert.equal(draft?.name, "ada-helper");
  assert.equal(draft?.kind, "skill");
  assert.equal(draft?.status, "pending");
  assert.deepEqual(draft?.tags, []);
  assert.deepEqual(draft?.references, []);
  assert.equal(draft?.replaced, false);
  assert.equal(draft?.approved_at, null);
});

test("extractCreationDraft keeps tags and references, defaulting a reference's missing size/content", () => {
  const draft = extractCreationDraft([
    toolResult({
      ...BASE,
      tags: ["math", "proofs"],
      references: [{ path: "references/notes.md" }, { path: "references/table.csv", size: 512, content: "a,b\n1,2\n" }],
      status: "created",
      created_name: "ada-helper",
      replaced: true,
      created_at: "2026-01-01T00:00:00Z",
      approved_at: "2026-01-01T00:05:00Z",
    }),
  ]);
  assert.deepEqual(draft?.tags, ["math", "proofs"]);
  assert.equal(draft?.references.length, 2);
  assert.equal(draft?.references[0].size, 0);
  assert.equal(draft?.references[0].content, "");
  assert.equal(draft?.references[1].content, "a,b\n1,2\n");
  assert.equal(draft?.status, "created");
  assert.equal(draft?.replaced, true);
});

test("extractCreationDraft rejects malformed ids, unknown kinds, and takes the latest of several", () => {
  assert.equal(
    extractCreationDraft([toolResult({ ...BASE, draft_id: "../escape" })]),
    null,
  );
  assert.equal(
    extractCreationDraft([toolResult({ ...BASE, kind: "worksheet" })]),
    null,
  );
  const draft = extractCreationDraft([
    toolResult({ ...BASE, name: "first-try" }),
    toolResult({ ...BASE, name: "revised" }),
  ]);
  assert.equal(draft?.name, "revised");
});
