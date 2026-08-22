import test from "node:test";
import assert from "node:assert/strict";

import {
  cleanTextForSpeech,
  detectTextLanguage,
  getKidsPronunciationAudioUrl,
  shouldUsePronunciationStream,
  splitTextIntoSentences,
  subscribeKidsSpeechState,
  stopKidsSpeech,
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

test("splitTextIntoSentences chunks English paragraphs correctly", () => {
  const story = "Plums are in a tree. Mat and Sam get the plums. Are the plums good now? The plums are hard.";
  const sentences = splitTextIntoSentences(story);
  assert.deepEqual(sentences, [
    "Plums are in a tree.",
    "Mat and Sam get the plums.",
    "Are the plums good now?",
    "The plums are hard.",
  ]);
});

test("splitTextIntoSentences chunks Chinese text correctly", () => {
  const storyZh = "树上有李子。麦特和山姆去摘李子。李子现在好吃吗？李子还很硬。";
  const sentences = splitTextIntoSentences(storyZh);
  assert.deepEqual(sentences, [
    "树上有李子。",
    "麦特和山姆去摘李子。",
    "李子现在好吃吗？",
    "李子还很硬。",
  ]);
});

test("stopKidsSpeech resets playback state without throwing", () => {
  assert.doesNotThrow(() => {
    stopKidsSpeech();
  });
});
