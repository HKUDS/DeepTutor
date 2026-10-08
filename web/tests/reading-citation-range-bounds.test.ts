import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { findLocatorCitations, linkifyLocatorCitations } from "../lib/reading-citations";

for (const citation of [
  "[p.9007199254740992-9007199254740994]",
  `[p.${"9".repeat(310)}-${"9".repeat(311)}]`,
]) {
  test(`out-of-range citation terminates without a link: ${citation.slice(0, 45)}`, () => {
    // Execute the real parser in a native child so a regression cannot hang the runner.
    const result = spawnSync(process.execPath, [
      "-r", path.resolve("scripts/register-node-test-aliases.cjs"),
      "-e",
      `const {findLocatorCitations,linkifyLocatorCitations}=require(${JSON.stringify(require.resolve("../lib/reading-citations"))});
       const text=${JSON.stringify(citation)};
       process.stdout.write(JSON.stringify({citations:findLocatorCitations(text),text:linkifyLocatorCitations(text)}));`,
    ], { encoding: "utf8", timeout: 2000 });
    assert.equal(result.error, undefined, result.error?.message);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), { citations: [], text: citation });
  });
}

test("unsafe individual locators remain plain text while ordinary ranges still link", () => {
  assert.deepEqual(findLocatorCitations("[p.9007199254740992]"), []);
  assert.equal(linkifyLocatorCitations("[p.3-5]"), "[p.3,4,5](#dt-locator-3)");
  assert.equal(linkifyLocatorCitations("[p.5-3]"), "[p.3,4,5](#dt-locator-3)");
});
