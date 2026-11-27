import test from "node:test";
import assert from "node:assert/strict";
import { clientEditionLabel, normalizeVersionTag } from "../lib/version";

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

test("clientEditionLabel names the web client by default", () => {
  assert.equal(
    clientEditionLabel("1.7.0", "Mozilla/5.0 Chrome/140.0"),
    "Open DeepTutor Web v1.7.0",
  );
});

const SHELL = "Mozilla/5.0 Chrome/140.0 Electron/45.1.0 OpenDeepTutor/1.7.1";

test("clientEditionLabel names each desktop edition", () => {
  assert.equal(
    clientEditionLabel("1.7.1", `${SHELL} (macOS; arm64)`),
    "Open DeepTutor for MacOS with Apple Silicon v1.7.1",
  );
  assert.equal(
    clientEditionLabel("1.7.1", `${SHELL} (macOS; x64)`),
    "Open DeepTutor for MacOS with Intel Silicon v1.7.1",
  );
  assert.equal(
    clientEditionLabel("1.7.1", `${SHELL} (Windows; x64)`),
    "Open DeepTutor for Windows v1.7.1",
  );
});

test("clientEditionLabel has short forms for tight spaces", () => {
  assert.equal(
    clientEditionLabel("1.7.1", `${SHELL} (macOS; arm64)`, "short"),
    "MacOS (Apple Silicon) v1.7.1",
  );
  assert.equal(
    clientEditionLabel("1.7.1", `${SHELL} (macOS; x64)`, "short"),
    "MacOS (Intel) v1.7.1",
  );
  assert.equal(clientEditionLabel("1.7.1", "Mozilla/5.0", "short"), "Web v1.7.1");
});

test("clientEditionLabel still recognises 1.7.0 shells", () => {
  assert.equal(
    clientEditionLabel("1.7.0", `${SHELL} (macOS)`),
    "Open DeepTutor for MacOS v1.7.0",
  );
});

test("clientEditionLabel omits an unparseable version", () => {
  assert.equal(clientEditionLabel(undefined, ""), "Open DeepTutor Web");
});
