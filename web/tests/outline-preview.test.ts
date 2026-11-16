import assert from "node:assert/strict";
import test from "node:test";

import type { StreamEvent } from "../features/chat/model/protocol";
import {
  modeHandoffFingerprint,
  modeHandoffKnowledgePoint,
  modeHandoffMode,
  modeHandoffSession,
  outlinePreviewOnMessage,
  shouldFollowModeHandoff,
} from "../lib/outline-preview";

function toolResult(metadata: Record<string, unknown>): StreamEvent {
  return {
    type: "tool_result",
    source: "chat",
    stage: "responding",
    content: "",
    metadata: { tool_metadata: metadata },
    session_id: "session-1",
    turn_id: "turn-1",
    seq: 1,
    timestamp: 0,
  };
}

test("an outline button appears only for an unsaved revision preview", () => {
  const saved = outlinePreviewOnMessage([
    toolResult({ mastery_revision_preview: { status: "committed", preview_id: 3 } }),
  ]);
  const preview = outlinePreviewOnMessage([
    toolResult({
      mastery_revision_preview: { status: "preview_only_not_saved", preview_id: 8 },
    }),
  ]);
  assert.equal(saved, null);
  assert.deepEqual(preview, { previewId: 8 });
  assert.equal(outlinePreviewOnMessage(undefined), null);
});

test("a mode handoff names the session the page should open", () => {
  const sessionId = modeHandoffSession([
    toolResult({ mastery_mode: { status: "open_session", session_id: "study-2" } }),
  ]);
  assert.equal(sessionId, "study-2");
  assert.equal(
    modeHandoffSession([toolResult({ mastery_mode: { status: "refused", session_id: "nope" } })]),
    "",
  );
});

test("a mode handoff names the knowledge point it opened", () => {
  // The page uses this to tell a same-point mode change (follow) from the tutor
  // advancing the path to the next point (do not follow).
  assert.equal(
    modeHandoffKnowledgePoint([
      toolResult({
        mastery_mode: {
          status: "open_session",
          session_id: "study-2",
          knowledge_point_id: "kp2",
        },
      }),
    ]),
    "kp2",
  );
  assert.equal(modeHandoffKnowledgePoint(undefined), "");
});

test("a mode handoff names the mode it switched into", () => {
  assert.equal(
    modeHandoffMode([
      toolResult({
        mastery_mode: { status: "open_session", session_id: "study-2", mode: "study" },
      }),
    ]),
    "study",
  );
  assert.equal(modeHandoffMode(undefined), "");
});

test("reopening a knowledge point does not follow a historical mode handoff", () => {
  const messages = [
    {
      role: "assistant",
      id: 80,
      events: [toolResult({ mastery_mode: { status: "open_session", session_id: "memory-session" } })],
    },
  ];
  const first = modeHandoffFingerprint(messages, "kp0-session");
  assert.equal(first.target, "memory-session");
  assert.equal(
    shouldFollowModeHandoff({
      ...first,
      sessionId: "kp0-session",
      baselineFingerprint: "",
    }),
    false,
  );
  assert.equal(
    shouldFollowModeHandoff({
      ...first,
      sessionId: "kp0-session",
      baselineFingerprint: first.fingerprint,
    }),
    false,
  );
});

test("a new mode handoff after the session is open is followed", () => {
  const earlier = modeHandoffFingerprint([], "kp0-session");
  const later = modeHandoffFingerprint(
    [
      {
        role: "assistant",
        id: 81,
        events: [toolResult({ mastery_mode: { status: "open_session", session_id: "review-session" } })],
      },
    ],
    "kp0-session",
  );
  assert.equal(
    shouldFollowModeHandoff({
      ...later,
      sessionId: "kp0-session",
      baselineFingerprint: earlier.fingerprint,
    }),
    true,
  );
});
