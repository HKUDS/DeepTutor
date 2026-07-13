import test from "node:test";
import assert from "node:assert/strict";
import { normalizeVersionTag } from "../lib/version";

test("normalizeVersionTag accepts bare semver", () => {
  assert.equal(normalizeVersionTag("1.4.0"), "v1.4.0");
});

test("normalizeVersionTag keeps the v prefix", () => {
  assert.equal(normalizeVersionTag("v1.4.0"), "v1.4.0");
});

test("normalizeVersionTag supports PEP 440-style pre-releases", () => {
  assert.equal(normalizeVersionTag("v1.0.0-beta.4"), "v1.0.0-beta.4");
  assert.equal(normalizeVersionTag("1.0.0rc1"), "v1.0.0rc1");
});

test("normalizeVersionTag rejects unparseable inputs", () => {
  assert.equal(normalizeVersionTag(""), null);
  assert.equal(normalizeVersionTag(undefined), null);
  assert.equal(normalizeVersionTag("abc1234"), null);
  assert.equal(normalizeVersionTag("v1.2.3-5-gabc1234"), null);
});
