import test from "node:test";
import assert from "node:assert/strict";

import {
  looksLikeCrisisRedirect,
  parseRoomIdFromContent,
} from "../lib/psych-crisis-transcript";

test("parseRoomIdFromContent extracts id from room_id=abc-123", () => {
  assert.equal(parseRoomIdFromContent("join room_id=abc-123 please"), "abc-123");
  assert.equal(parseRoomIdFromContent("no room here"), null);
});

test("looksLikeCrisisRedirect true on real EN redirect snippet", () => {
  const en =
    "I am concerned you may be in danger. This system cannot provide crisis intervention. ";
  assert.equal(looksLikeCrisisRedirect(en), true);
  assert.equal(looksLikeCrisisRedirect("ordinary counseling reply"), false);
});
