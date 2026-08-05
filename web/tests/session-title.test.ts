import test from "node:test";
import assert from "node:assert/strict";

import { isPlaceholderSessionTitle } from "../lib/session-title";

test("empty and backend-default session titles are placeholders", () => {
  assert.equal(isPlaceholderSessionTitle(""), true);
  assert.equal(isPlaceholderSessionTitle("  New conversation  "), true);
});

test("user and generated session titles remain business data", () => {
  assert.equal(isPlaceholderSessionTitle("New Conversation"), false);
  assert.equal(isPlaceholderSessionTitle("傅里叶变换"), false);
});
