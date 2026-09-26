import assert from "node:assert/strict";
import test from "node:test";
import { sessionRoute } from "../lib/mastery-session";
import { normalizeWorkspaceMode } from "../lib/workspace-mode";
import { capabilityForPath } from "../lib/capability-routes";
import type { SessionSummary } from "../lib/session-api";

test("Watching links retain their owning workspace, including legacy sessions", () => {
  for (const preferences of [
    { workspace_mode: "immersive_watching" as const },
    { capability: "immersive_watching" },
  ]) {
    assert.equal(
      sessionRoute({ session_id: "lesson 1", preferences } as SessionSummary),
      "/learning/watching/lesson%201?dt_workspace=",
    );
  }
  assert.equal(
    sessionRoute({
      session_id: "chat",
      preferences: { timed_media_id: "stale" },
    } as SessionSummary),
    "/chat/chat?dt_workspace=",
  );
  assert.equal(
    normalizeWorkspaceMode("", "immersive_watching"),
    "immersive_watching",
  );
  assert.equal(capabilityForPath("/learning/watching/lesson"), "llm");
  assert.equal(capabilityForPath("/watching-other"), null);
});
