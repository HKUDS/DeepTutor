import test from "node:test";
import assert from "node:assert/strict";

import {
  getPronunciationState,
  isPronouncingWord,
  playWordPronunciation,
  speakWord,
  stopPronunciation,
  subscribePronunciationState,
  wordPronunciationSupported,
} from "../lib/word-pronunciation";

test("pronunciation state and subscription manage listeners cleanly", () => {
  let latestState = getPronunciationState();
  const unsubscribe = subscribePronunciationState((state) => {
    latestState = state;
  });

  assert.equal(latestState.isPlaying, false);
  assert.equal(latestState.word, null);
  assert.equal(latestState.accent, null);
  assert.equal(isPronouncingWord("hello"), false);

  stopPronunciation();
  assert.equal(latestState.isPlaying, false);

  unsubscribe();
});

test("wordPronunciationSupported degrades gracefully in Node environment", () => {
  assert.equal(wordPronunciationSupported(), false);
  assert.equal(speakWord("test"), false);
});

test("playWordPronunciation returns false for empty tokens", async () => {
  const result = await playWordPronunciation("   ", "en-US");
  assert.equal(result, false);
});
