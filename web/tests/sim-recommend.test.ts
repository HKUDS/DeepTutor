import test from "node:test";
import assert from "node:assert/strict";

import { parseSimRecommendation } from "../lib/sim-recommend";

test("parseSimRecommendation reads kind, target_id, reason from metadata", () => {
  const rec = parseSimRecommendation({
    kind: "skill_drill",
    target_id: "reflective-listening",
    reason: "High recent intensity — pace with a gentle skill drill first",
    priority: 1,
  });
  assert.deepEqual(rec, {
    kind: "skill_drill",
    targetId: "reflective-listening",
    reason: "High recent intensity — pace with a gentle skill drill first",
  });
});

test("parseSimRecommendation returns null when kind or target_id missing", () => {
  assert.equal(parseSimRecommendation({ kind: "skill_drill" }), null);
  assert.equal(parseSimRecommendation({ target_id: "grief-silence" }), null);
  assert.equal(parseSimRecommendation({}), null);
  assert.equal(parseSimRecommendation(null), null);
  assert.equal(parseSimRecommendation(undefined), null);
});

test("parseSimRecommendation does not invent ids from unrelated metadata", () => {
  assert.equal(
    parseSimRecommendation({ session_id: "abc", capability: "counsel_sim" }),
    null,
  );
});
