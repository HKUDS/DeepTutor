import assert from "node:assert/strict";
import test from "node:test";

import {
  buildStartTurnInput,
  legacySendMessageInput,
} from "../features/chat/controllers/buildStartTurnInput";
import type { StartTurnInput } from "../features/chat/model/start-turn";
import { ApiError } from "../shared/api/errors";

test("plain, quiz, research, and visualize turns use one typed mapper", () => {
  const matrix: StartTurnInput[] = [
    { content: "hello", capability: "chat" },
    {
      content: "quiz me",
      capability: "deep_question",
      capabilityConfig: { difficulty: "medium" },
      allowedCapabilityConfigKeys: ["difficulty"],
    },
    {
      content: "research",
      capability: "deep_research",
      capabilityConfig: { breadth: 3 },
      allowedCapabilityConfigKeys: ["breadth"],
    },
    {
      content: "draw",
      capability: "visualize",
      capabilityConfig: { render_type: "mermaid" },
      allowedCapabilityConfigKeys: ["render_type"],
    },
  ];
  for (const input of matrix) {
    const wire = buildStartTurnInput(input);
    assert.equal(wire.type, "start_turn");
    assert.equal(wire.protocol_version, "2.0");
    assert.equal(wire.capability, input.capability);
  }
});

test("course, Reading, Watching, Mastery, references, edit, and budget are explicit", () => {
  const wire = buildStartTurnInput({
    content: "continue",
    sessionId: "session-1",
    workspaceMode: "immersive_reading",
    courseId: "course-1",
    masteryPathId: "path-1",
    readingWorkspaceId: "reading-1",
    readingMaterialId: "material-1",
    readingMaterialRevision: 2,
    readingViewport: { locator: 4, selection: "proof" },
    timedMediaId: "video-1",
    timedMediaViewport: { time_seconds: 12.5 },
    parentMessageId: 9,
    subagentConsultBudget: 3,
    notebookReferences: [{ notebook_id: "nb", record_ids: ["r1"] }],
    bookReferences: [{ book_id: "book", page_ids: ["p1"] }],
    readingReferences: [
      { material_id: "material-1", revision: 2, locators: [4] },
    ],
    attachments: [{ type: "document", filename: "notes.pdf", url: "/a" }],
  });
  assert.equal(wire.course_id, "course-1");
  assert.equal(wire.parent_message_id, 9);
  assert.equal(wire.subagent_consult_budget, 3);
  assert.equal(wire.reading_viewport?.locator, 4);
  assert.equal(wire.timed_media_viewport?.time_seconds, 12.5);
});

test("waiting-input replies stay commands and runtime config cannot leak into capability config", () => {
  assert.throws(
    () =>
      buildStartTurnInput({
        content: "bad",
        capabilityConfig: { _course_id: "hidden" },
      }),
    (error) => error instanceof ApiError && error.code === "invalid_turn_input",
  );
  assert.throws(
    () =>
      buildStartTurnInput({
        content: "bad",
        capabilityConfig: { unexpected: true },
        allowedCapabilityConfigKeys: ["difficulty"],
      }),
    /Unsupported/,
  );

  const wire = buildStartTurnInput({ content: "ok", courseId: "course-1" });
  assert.equal("_course_id" in (wire.config ?? {}), false);
  assert.equal("subagent_consult_budget" in (wire.config ?? {}), false);
});

test("optional routing fields preserve omitted versus explicit null", () => {
  const omitted = buildStartTurnInput({ content: "append" });
  const explicit = buildStartTurnInput({
    content: "root edit",
    capability: null,
    parentMessageId: null,
  });

  assert.equal("parent_message_id" in omitted, false);
  assert.equal(explicit.parent_message_id, null);
  assert.equal(explicit.capability, null);
});

test("the positional compatibility adapter produces object-shaped input", () => {
  const input = legacySendMessageInput(
    { content: "legacy", config: { difficulty: "hard" } },
    {
      capability: "deep_question",
      allowedCapabilityConfigKeys: ["difficulty"],
      sessionId: "session-1",
    },
  );
  assert.equal(input.content, "legacy");
  assert.deepEqual(input.capabilityConfig, { difficulty: "hard" });
  assert.equal(buildStartTurnInput(input).session_id, "session-1");
});
