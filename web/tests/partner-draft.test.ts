import assert from "node:assert/strict";
import test from "node:test";

import { extractPartnerDraft } from "@/lib/partner-draft";
import type { StreamEvent } from "@/features/chat/model/protocol";

function toolResult(partnerDraft: Record<string, unknown>): StreamEvent {
  return {
    type: "tool_result",
    source: "chat",
    stage: "responding",
    seq: 1,
    content: "ok",
    metadata: { tool_metadata: { partner_draft: partnerDraft } },
    timestamp: Date.now(),
  };
}

test("extractPartnerDraft reads a valid review card payload", () => {
  const draft = extractPartnerDraft([
    toolResult({
      draft_id: "a".repeat(32),
      owner_id: "u-alice",
      name: "Ada",
      description: "Math mentor",
      soul: "# Soul\nBe rigorous.",
      language: "en",
      emoji: "📐",
      color: "#3366aa",
      status: "pending",
      version: 1,
    }),
  ]);
  assert.equal(draft?.name, "Ada");
  assert.equal(draft?.status, "pending");
});

test("extractPartnerDraft rejects malformed ids and incomplete profiles", () => {
  assert.equal(
    extractPartnerDraft([
      toolResult({ draft_id: "../escape", name: "Ada", soul: "profile" }),
    ]),
    null,
  );
  assert.equal(
    extractPartnerDraft([
      toolResult({ draft_id: "b".repeat(32), name: "Ada", soul: "" }),
    ]),
    null,
  );
});
