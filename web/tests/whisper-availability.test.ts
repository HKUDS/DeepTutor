import test from "node:test";
import assert from "node:assert/strict";
import {
  REQUIRED_WHISPER_CAPABILITIES,
  hasWhisperCapabilities,
} from "../lib/whisper-availability";

test("whisper requires both seat capabilities", () => {
  assert.deepEqual(REQUIRED_WHISPER_CAPABILITIES, [
    "whisper_visitor",
    "whisper_trainee",
  ]);
});

test("whisper availability accepts a complete plugin catalog", () => {
  assert.equal(
    hasWhisperCapabilities({
      capabilities: [
        { name: "chat" },
        { name: "whisper_visitor" },
        { name: "whisper_trainee" },
      ],
    }),
    true,
  );
});

test("whisper availability rejects partial plugin catalogs", () => {
  assert.equal(
    hasWhisperCapabilities({
      capabilities: [{ name: "chat" }, { name: "whisper_visitor" }],
    }),
    false,
  );
});

test("whisper availability rejects malformed payloads safely", () => {
  for (const payload of [null, {}, { capabilities: "whisper_visitor" }]) {
    assert.equal(hasWhisperCapabilities(payload), false);
  }
});
