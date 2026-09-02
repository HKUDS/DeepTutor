import assert from "node:assert/strict";
import test from "node:test";

import { masteryPathIdOf, readingWorkspaceIdOf } from "../lib/mastery-session";
import type { SessionSummary } from "../lib/session-api";
import { workspaceActionNeedsConfiguration } from "../lib/workspace-mode";

function session(preferences: SessionSummary["preferences"]): SessionSummary {
  return {
    id: "session-1",
    session_id: "session-1",
    title: "Learning session",
    created_at: 1,
    updated_at: 1,
    message_count: 1,
    last_message: "hello",
    preferences,
  };
}

test("mastery ownership survives switching the per-turn action", () => {
  const item = session({
    workspace_mode: "mastery_path",
    mastery_path_id: "path-42",
    capability: "deep_research",
  });

  assert.equal(masteryPathIdOf(item), "path-42");
});

test("reading ownership survives switching the per-turn action", () => {
  const item = session({
    workspace_mode: "immersive_reading",
    reading_workspace_id: "reading-42",
    capability: "visualize",
  });

  assert.equal(readingWorkspaceIdOf(item), "reading-42");
});

test("capability and retired session-kind fields do not claim workspace ownership", () => {
  assert.equal(
    masteryPathIdOf(
      session({ capability: "mastery_path", mastery_path_id: "legacy-path" }),
    ),
    "",
  );
  assert.equal(
    readingWorkspaceIdOf(
      session({
        capability: "immersive_reading",
        session_kind: "immersive_reading",
        reading_workspace_id: "legacy-reading",
      }),
    ),
    "",
  );
});

test("unrelated sessions do not inherit stale learning ids", () => {
  assert.equal(
    masteryPathIdOf(
      session({ capability: "chat", mastery_path_id: "stale-path" }),
    ),
    "",
  );
  assert.equal(
    readingWorkspaceIdOf(
      session({ capability: "chat", reading_workspace_id: "stale-reading" }),
    ),
    "",
  );
});

test("configured workspace actions do not bypass their settings", () => {
  assert.equal(workspaceActionNeedsConfiguration("deep_question"), true);
  assert.equal(workspaceActionNeedsConfiguration("visualize"), true);
  assert.equal(workspaceActionNeedsConfiguration("deep_research"), true);
  assert.equal(workspaceActionNeedsConfiguration("deep_solve"), false);
  assert.equal(workspaceActionNeedsConfiguration(""), false);
});
