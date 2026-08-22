import test from "node:test";
import assert from "node:assert/strict";

import {
  cleanTextForSpeech,
  detectTextLanguage,
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

test("kids pronunciation cleans markdown and detects language accurately", () => {
  const markdownSample = "### 探索范围：我们能看到什么？\n\n* **光的波粒二象性**：解释为什么光既是波又是粒子（光子）。\n\n💡 提示：重点关注 $h/4\\pi$";
  const cleaned = cleanTextForSpeech(markdownSample);
  assert.doesNotMatch(cleaned, /###|\*\*|\*|💡|\$/);
  assert.match(cleaned, /探索范围：我们能看到什么？/);
  assert.match(cleaned, /光的波粒二象性：解释为什么光既是波又是粒子/);
  assert.equal(detectTextLanguage(cleaned), "zh-CN");
  assert.equal(detectTextLanguage("The little plum is on the mat."), "en-US");
});
