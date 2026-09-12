import assert from "node:assert/strict";
import { test } from "node:test";
import { resolveReadingAgeMode } from "@/lib/reading-age-presentation";

test("learner profile age chooses an age-specific presentation", () => {
  assert.equal(resolveReadingAgeMode(3), "early");
  assert.equal(resolveReadingAgeMode(6), "early");
  assert.equal(resolveReadingAgeMode(7), "young");
  assert.equal(resolveReadingAgeMode(8), "young");
  assert.equal(resolveReadingAgeMode(12), "older");
  assert.equal(resolveReadingAgeMode(13), "default");
  assert.equal(resolveReadingAgeMode(120), "default");
});

test("learning policy band is the fallback when profile age is absent", () => {
  assert.equal(resolveReadingAgeMode(null, "6-8"), "young");
  assert.equal(resolveReadingAgeMode(undefined, "9-12"), "older");
  assert.equal(resolveReadingAgeMode(undefined, "13-15"), "default");
  assert.equal(resolveReadingAgeMode(undefined, "unexpected"), "default");
});

test("invalid profile ages fall back to policy data", () => {
  assert.equal(resolveReadingAgeMode(2, "6-8"), "young");
  assert.equal(resolveReadingAgeMode(3.5, "9-12"), "older");
});
