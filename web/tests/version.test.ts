import test from "node:test";
import assert from "node:assert/strict";
import { normalizeVersionTag, parseBuild, unknownBuild } from "../lib/version";

test("parseBuild normalizes clean release tags", () => {
  assert.deepEqual(parseBuild("1.2.3"), {
    tag: "v1.2.3",
    isDev: false,
    isDirty: false,
    display: "v1.2.3",
    raw: "1.2.3",
    commitsAhead: null,
    commit: null,
  });
});

test("parseBuild handles commits ahead of a release tag", () => {
  assert.deepEqual(parseBuild("v1.2.3-5-gabc1234"), {
    tag: "v1.2.3",
    isDev: true,
    isDirty: false,
    display: "v1.2.3+5",
    raw: "v1.2.3-5-gabc1234",
    commitsAhead: 5,
    commit: "abc1234",
  });
});

test("parseBuild preserves dirty worktree state", () => {
  assert.deepEqual(parseBuild("v1.2.3-5-gabc1234-dev"), {
    tag: "v1.2.3",
    isDev: true,
    isDirty: true,
    display: "v1.2.3+5\u00b7dev",
    raw: "v1.2.3-5-gabc1234-dev",
    commitsAhead: 5,
    commit: "abc1234",
  });
});

test("parseBuild supports prerelease tags", () => {
  assert.equal(parseBuild("v1.0.0-beta.4")?.tag, "v1.0.0-beta.4");
  assert.equal(
    parseBuild("v1.0.0-beta.4-2-gabc1234")?.display,
    "v1.0.0-beta.4+2",
  );
});

test("normalizeVersionTag only returns exact version tags", () => {
  assert.equal(normalizeVersionTag("1.2.3"), "v1.2.3");
  assert.equal(normalizeVersionTag("v1.2.3-dev"), null);
  assert.equal(normalizeVersionTag("v1.2.3-5-gabc1234"), null);
});

test("unknownBuild keeps an unknown raw version visible", () => {
  assert.deepEqual(unknownBuild("abc1234"), {
    tag: null,
    isDev: true,
    isDirty: false,
    display: "abc1234",
    raw: "abc1234",
    commitsAhead: null,
    commit: null,
  });
});
