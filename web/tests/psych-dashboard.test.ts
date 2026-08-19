import test from "node:test";
import assert from "node:assert/strict";

import {
  observeDebriefHref,
  psychSessionHref,
} from "../lib/psych-dashboard";

test("psychSessionHref maps session kinds to workspace routes", () => {
  assert.equal(psychSessionHref("counsel", "abc"), "/counsel?session_hint=abc");
  assert.equal(psychSessionHref("sim", "sim-1"), "/sim");
  assert.equal(psychSessionHref("whisper", "room42"), "/whisper?room_hint=room42");
  assert.equal(psychSessionHref("intake", "room99"), "/intake?room_hint=room99");
});

test("observeDebriefHref encodes counsel session id", () => {
  assert.equal(observeDebriefHref("closed-counsel"), "/observe?counsel_id=closed-counsel");
});
