import test from "node:test";
import assert from "node:assert/strict";

import {
  getKidsPronunciationAudioUrl,
  shouldUsePronunciationStream,
  subscribeKidsSpeechState,
} from "../lib/kids-learning/pronunciation";

test("kids pronunciation uses the stable cached audio stream", () => {
  assert.equal(
    getKidsPronunciationAudioUrl("Plum!"),
    "https://dict.youdao.com/dictvoice?audio=plum&type=2",
  );
  assert.equal(shouldUsePronunciationStream("plum"), true);
  assert.equal(shouldUsePronunciationStream("small sweet fruit"), true);
  assert.equal(
    shouldUsePronunciationStream("What does the word plum mean in this story?"),
    false,
  );
});

test("kids pronunciation exposes one shared playback state", () => {
  const seen: boolean[] = [];
  const unsubscribe = subscribeKidsSpeechState((state) => seen.push(state.isPlaying));
  unsubscribe();

  assert.deepEqual(seen, [false]);
});
