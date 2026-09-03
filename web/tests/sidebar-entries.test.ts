import test from "node:test";
import assert from "node:assert/strict";

import { buildSidebarEntries } from "../lib/sidebar-entries";
import { organizeSessionTree } from "../lib/session-organization";
import type { SessionSummary } from "../lib/session-api";
import type { SessionPreferences } from "../lib/session-api";

let clock = 2000;

/** A root conversation, newest first as the server lists them. */
function session(
  id: string,
  preferences: SessionPreferences = {},
  extra: Partial<SessionSummary> = {},
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
    ...extra,
  };
}

function inTopic(id: string, pathId: string): SessionSummary {
  return session(id, {
    workspace_mode: "mastery_path",
    mastery_path_id: pathId,
  });
}

function inCollection(id: string, workspaceId: string): SessionSummary {
  return session(id, {
    workspace_mode: "immersive_reading",
    reading_workspace_id: workspaceId,
  });
}

const TOPICS = [{ path_id: "langgraph", name: "LangGraph", emoji: "" }];
const COLLECTIONS = [{ workspace_id: "shelf", title: "Papers" }];

test("a group sits in the slot of the newest conversation inside it", () => {
  const entries = buildSidebarEntries({
    roots: [
      session("chat-new"),
      inTopic("study-new", "langgraph"),
      session("chat-old"),
      inTopic("study-old", "langgraph"),
    ],
    masteryTopics: TOPICS,
  });
  assert.deepEqual(
    entries.map((entry) => `${entry.kind}:${entry.id}`),
    ["session:chat-new", "group:langgraph", "session:chat-old"],
  );
});

test("a group is one entry holding its rows in arrival order", () => {
  const entries = buildSidebarEntries({
    roots: [
      inCollection("read-new", "shelf"),
      session("chat"),
      inCollection("read-old", "shelf"),
    ],
    readingCollections: COLLECTIONS,
  });
  const group = entries[0];
  assert.equal(group.kind, "group");
  if (group.kind !== "group") return;
  assert.equal(group.group, "reading");
  assert.equal(group.label, "Papers");
  assert.deepEqual(
    group.rows.map((row) => row.session_id),
    ["read-new", "read-old"],
  );
  assert.equal(entries.length, 2);
});

test("conversations whose group label is gone are listed on their own", () => {
  // A topic index that failed to load, or a deleted collection: filing the
  // conversation under a heading nobody can name would lose it entirely.
  const entries = buildSidebarEntries({
    roots: [inTopic("study", "langgraph"), inCollection("read", "shelf")],
  });
  assert.deepEqual(
    entries.map((entry) => `${entry.kind}:${entry.id}`),
    ["session:study", "session:read"],
  );
});

test("a study conversation reached from a course still files under its topic", () => {
  const entries = buildSidebarEntries({
    roots: [
      session("study", {
        workspace_mode: "mastery_path",
        mastery_path_id: "langgraph",
        course_id: "algebra",
      }),
    ],
    masteryTopics: TOPICS,
    courses: [
      {
        id: "algebra",
        name: "Algebra",
        description: "",
        color: "#f00",
        created_at: 1,
        updated_at: 1,
        instructions: "",
        agent_notes: "",
        default_capability: "",
        default_persona: "",
      } as never,
    ],
  });
  assert.deepEqual(
    entries.map((entry) => entry.id),
    ["langgraph"],
  );
});

test("a hand-dragged order moves a group above a conversation", () => {
  const roots = [
    session("chat-a"),
    session("chat-b"),
    inTopic("s", "langgraph"),
  ];
  const entries = buildSidebarEntries({
    roots,
    masteryTopics: TOPICS,
    manualOrder: ["langgraph", "chat-a", "chat-b"],
  });
  assert.deepEqual(
    entries.map((entry) => entry.id),
    ["langgraph", "chat-a", "chat-b"],
  );
});

test("an order stored before groups were draggable still applies", () => {
  // Orders saved by the previous sidebar hold conversation ids only. Those
  // conversations keep their arrangement; the groups stay where recency put
  // them rather than the whole order being discarded.
  const entries = buildSidebarEntries({
    roots: [
      session("chat-a"),
      inTopic("s", "langgraph"),
      session("chat-b"),
      session("chat-c"),
    ],
    masteryTopics: TOPICS,
    manualOrder: ["chat-c", "chat-a", "chat-b"],
  });
  assert.deepEqual(
    entries.map((entry) => entry.id),
    ["chat-c", "langgraph", "chat-a", "chat-b"],
  );
});

test("a streaming conversation outranks a newer idle one, pins outrank both", () => {
  const idle = session("idle");
  const running = session("running");
  const pinned = session("pinned", { pinned: true });
  const { roots } = organizeSessionTree(
    [idle, running, pinned],
    true,
    new Set(["running"]),
  );
  assert.deepEqual(
    roots.map((row) => row.session_id),
    ["pinned", "running", "idle"],
  );
});

test("a conversation stuck at running in the database does not float up", () => {
  // A turn that died without a terminal event leaves "running" behind forever.
  // Only the caller's live runtime lifts a row, so the dead one stays put.
  const fresh = session("fresh");
  const zombie = session("zombie", {}, { status: "running" });
  const { roots } = organizeSessionTree([fresh, zombie], true);
  assert.deepEqual(
    roots.map((row) => row.session_id),
    ["fresh", "zombie"],
  );
});

test("a streaming conversation carries its group to the top with it", () => {
  const chat = session("chat");
  const study = inTopic("study", "langgraph");
  const entries = buildSidebarEntries({
    roots: organizeSessionTree([chat, study], true, new Set(["study"])).roots,
    masteryTopics: TOPICS,
  });
  assert.deepEqual(
    entries.map((entry) => entry.id),
    ["langgraph", "chat"],
  );
});
