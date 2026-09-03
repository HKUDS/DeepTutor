import test from "node:test";
import assert from "node:assert/strict";

import {
  archiveCount,
  collectArchivedConversations,
} from "../lib/session-archive";
import type { SessionPreferences, SessionSummary } from "../lib/session-api";

let clock = 2000;

function session(
  id: string,
  preferences: SessionPreferences = {},
): SessionSummary {
  clock -= 1;
  return {
    id,
    session_id: id,
    title: id,
    created_at: clock,
    updated_at: clock,
    message_count: 2,
    last_message: "",
    preferences,
  };
}

const TOPICS = [{ path_id: "langgraph", name: "LangGraph", emoji: "" }];
const COLLECTIONS = [{ workspace_id: "shelf", title: "Papers" }];

test("archived conversations sort into their own surface", () => {
  const buckets = collectArchivedConversations({
    sessions: [
      session("live"),
      session("chat", { archived: true }),
      session("study", {
        archived: true,
        workspace_mode: "mastery_path",
        mastery_path_id: "langgraph",
      }),
      session("read", {
        archived: true,
        workspace_mode: "immersive_reading",
        reading_workspace_id: "shelf",
      }),
    ],
    masteryTopics: TOPICS,
    readingCollections: COLLECTIONS,
  });
  assert.deepEqual(
    buckets.chat.map((row) => row.session.session_id),
    ["chat"],
  );
  assert.deepEqual(buckets.mastery[0].container, "LangGraph");
  assert.deepEqual(buckets.reading[0].container, "Papers");
  assert.equal(archiveCount(buckets), 3);
});

test("an active conversation never appears in the archive", () => {
  const buckets = collectArchivedConversations({
    sessions: [session("live"), session("also-live", { pinned: true })],
  });
  assert.equal(archiveCount(buckets), 0);
});

test("a conversation whose topic is gone is still listed, just unnamed", () => {
  // The topic index failed to load, or the path was deleted. Dropping the row
  // would leave the conversation with no surface at all.
  const buckets = collectArchivedConversations({
    sessions: [
      session("study", {
        archived: true,
        workspace_mode: "mastery_path",
        mastery_path_id: "vanished",
      }),
    ],
  });
  assert.equal(buckets.mastery.length, 1);
  assert.equal(buckets.mastery[0].container, "");
});

test("a tutor thread archived with its parent is not listed separately", () => {
  // The backend archives and restores those together, so a restore button of
  // its own would appear to do nothing.
  const buckets = collectArchivedConversations({
    sessions: [
      session("parent", { archived: true }),
      session("thread", { archived: true, parent_session_id: "parent" }),
    ],
  });
  assert.deepEqual(
    buckets.chat.map((row) => row.session.session_id),
    ["parent"],
  );
});

test("a tutor thread archived on its own is listed", () => {
  const buckets = collectArchivedConversations({
    sessions: [
      session("parent"),
      session("thread", { archived: true, parent_session_id: "parent" }),
    ],
  });
  assert.deepEqual(
    buckets.chat.map((row) => row.session.session_id),
    ["thread"],
  );
});

test("each surface lists its newest conversation first", () => {
  const older = session("older", { archived: true });
  const newer = session("newer", { archived: true });
  const buckets = collectArchivedConversations({
    sessions: [
      { ...older, updated_at: 10 },
      { ...newer, updated_at: 99 },
    ],
  });
  assert.deepEqual(
    buckets.chat.map((row) => row.session.session_id),
    ["newer", "older"],
  );
});
