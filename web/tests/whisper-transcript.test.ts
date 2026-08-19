import test from "node:test";
import assert from "node:assert/strict";

import {
  filterMessagesForSeat,
  looksLikeCrisisRedirect,
  looksLikeTraineeCrisisSummary,
  parseRoomIdFromContent,
  type WhisperMessage,
} from "../lib/whisper-transcript";

test("parseRoomIdFromContent extracts id from room_id=abc-123", () => {
  assert.equal(parseRoomIdFromContent("join room_id=abc-123 please"), "abc-123");
  assert.equal(parseRoomIdFromContent("no room here"), null);
});

test("visitor seat drops stage=whisper", () => {
  const messages: WhisperMessage[] = [
    { id: "1", role: "assistant", text: "hello", stage: "responding" },
    { id: "2", role: "assistant", text: "secret", stage: "whisper" },
  ];
  const filtered = filterMessagesForSeat(messages, "visitor");
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].id, "1");
});

test("trainee seat keeps whisper", () => {
  const messages: WhisperMessage[] = [
    { id: "1", role: "assistant", text: "hello", stage: "responding" },
    { id: "2", role: "assistant", text: "secret", stage: "whisper" },
  ];
  const filtered = filterMessagesForSeat(messages, "trainee");
  assert.equal(filtered.length, 2);
});

test("visitor drops source=whisper_trainee + stage=debrief", () => {
  const messages: WhisperMessage[] = [
    { id: "1", role: "assistant", text: "ok", stage: "responding" },
    {
      id: "2",
      role: "assistant",
      text: "debrief notes",
      source: "whisper_trainee",
      stage: "debrief",
    },
  ];
  const filtered = filterMessagesForSeat(messages, "visitor");
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].id, "1");
});

test("looksLikeCrisisRedirect true on real EN redirect snippet", () => {
  const en =
    "I am concerned you may be in danger. This system cannot provide crisis intervention. ";
  assert.equal(looksLikeCrisisRedirect(en), true);
  assert.equal(looksLikeCrisisRedirect("ordinary counseling reply"), false);
});

test("looksLikeTraineeCrisisSummary true on real _CRISIS_SUMMARY snippet", () => {
  const summary =
    "This room was closed for crisis referral. No further counseling or whispers.";
  assert.equal(looksLikeTraineeCrisisSummary(summary), true);
  assert.equal(looksLikeTraineeCrisisSummary("ordinary debrief"), false);
});
