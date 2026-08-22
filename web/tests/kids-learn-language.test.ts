import test from "node:test";
import assert from "node:assert/strict";
import {
  detectKidsReadingLanguage,
  kidsLearningCopy,
} from "../lib/kids-learning/learn-language";

test("kids learning language uses CJK dominance rather than stray English words", () => {
  const mixedChinese =
    "很多小朋友都看过Facebook创始人给女儿讲量子力学的照片。这里主要是中文内容。";
  assert.equal(detectKidsReadingLanguage(mixedChinese), "zh");
  assert.equal(detectKidsReadingLanguage("Mit sat in the sun."), "en");
  assert.equal(detectKidsReadingLanguage("", "zh"), "zh");
});

test("kids learning copy has matching keys in both languages", () => {
  const en = kidsLearningCopy("en");
  const zh = kidsLearningCopy("zh");
  assert.equal(en.learn, "Learn");
  assert.equal(zh.learn, "学习");
  assert.equal(en.reflection, "Think About It");
  assert.equal(zh.reflection, "想一想");
  for (const key of Object.keys(en)) {
    assert.ok(en[key as keyof typeof en].length > 0);
    assert.ok(zh[key as keyof typeof zh].length > 0);
  }
});
