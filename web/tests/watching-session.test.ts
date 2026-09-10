import assert from "node:assert/strict";
import test from "node:test";

import { capabilityForPath } from "../lib/capability-routes";
import { normalizeWorkspaceMode } from "../lib/workspace-mode";

test("legacy Watching sessions canonicalize to the Reading workspace", () => {
  assert.equal(normalizeWorkspaceMode("immersive_watching"), "immersive_reading");
  assert.equal(
    normalizeWorkspaceMode("", "immersive_watching"),
    "immersive_reading",
  );
});

test("stale timed-media provenance does not claim a workspace", () => {
  assert.equal(normalizeWorkspaceMode("", ""), null);
  assert.equal(capabilityForPath("/reading/lesson"), "llm");
  assert.equal(capabilityForPath("/watching-other"), null);
});
