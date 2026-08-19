import test from "node:test";
import assert from "node:assert/strict";

import {
  filterMessagesForSeat,
  looksLikeIntakeRoomEnded,
  looksLikeIntakeTraineeCrisisSummary,
  type IntakeMessage,
} from "../lib/intake-transcript";

test("visitor seat drops stage=supervisor", () => {
  const messages: IntakeMessage[] = [
    { id: "1", role: "assistant", text: "hello", stage: "responding" },
    { id: "2", role: "assistant", text: "coach", stage: "supervisor" },
  ];
  const filtered = filterMessagesForSeat(messages, "visitor");
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].id, "1");
});

test("trainee and supervisor seats keep supervisor notes", () => {
  const messages: IntakeMessage[] = [
    { id: "1", role: "assistant", text: "hello", stage: "responding" },
    { id: "2", role: "assistant", text: "coach", stage: "supervisor" },
  ];
  assert.equal(filterMessagesForSeat(messages, "trainee").length, 2);
  assert.equal(filterMessagesForSeat(messages, "supervisor").length, 2);
});

test("visitor drops source=intake_trainee + stage=debrief", () => {
  const messages: IntakeMessage[] = [
    { id: "1", role: "assistant", text: "ok", stage: "responding" },
    {
      id: "2",
      role: "assistant",
      text: "debrief notes",
      source: "intake_trainee",
      stage: "debrief",
    },
  ];
  const filtered = filterMessagesForSeat(messages, "visitor");
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].id, "1");
});

test("looksLikeIntakeTraineeCrisisSummary matches backend copy", () => {
  const summary =
    "This intake session was closed for crisis referral. No further supervisor coaching.";
  assert.equal(looksLikeIntakeTraineeCrisisSummary(summary), true);
  assert.equal(looksLikeIntakeTraineeCrisisSummary("ordinary debrief"), false);
});

test("looksLikeIntakeRoomEnded matches backend copy", () => {
  assert.equal(
    looksLikeIntakeRoomEnded(
      "This intake session has ended. Start a new room_id to continue.",
    ),
    true,
  );
  assert.equal(looksLikeIntakeRoomEnded("still open"), false);
});
