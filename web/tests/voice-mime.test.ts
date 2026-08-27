import test from "node:test";
import assert from "node:assert/strict";

import { stripAudioMimeParameters } from "../lib/voice-mime";

test("stripAudioMimeParameters drops MediaRecorder codec parameters", () => {
  assert.equal(
    stripAudioMimeParameters("audio/webm;codecs=opus"),
    "audio/webm",
  );
  assert.equal(stripAudioMimeParameters("audio/ogg; codecs=opus"), "audio/ogg");
});

test("stripAudioMimeParameters keeps a clean type and falls back", () => {
  assert.equal(stripAudioMimeParameters("audio/wav"), "audio/wav");
  assert.equal(stripAudioMimeParameters(""), "audio/webm");
  assert.equal(stripAudioMimeParameters(undefined), "audio/webm");
});
