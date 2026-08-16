import test from "node:test";
import assert from "node:assert/strict";

import {
  getPronunciationAudioUrl,
  getPronunciationState,
  isPronouncingWord,
  playWordPronunciation,
  speakWord,
  stopPronunciation,
  subscribePronunciationState,
  wordPronunciationSupported,
} from "../lib/word-pronunciation";

test("getPronunciationAudioUrl produces valid US and UK URLs", () => {
  const usUrl = getPronunciationAudioUrl("Hello", "en-US");
  assert.equal(usUrl, "https://dict.youdao.com/dictvoice?audio=hello&type=2");

  const ukUrl = getPronunciationAudioUrl("Hello", "en-GB");
  assert.equal(ukUrl, "https://dict.youdao.com/dictvoice?audio=hello&type=1");

  const cleanUrl = getPronunciationAudioUrl(" well-known! ", "en-US");
  assert.equal(cleanUrl, "https://dict.youdao.com/dictvoice?audio=well-known&type=2");
});

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
