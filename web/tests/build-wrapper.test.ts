import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const webRoot = process.cwd();
const read = (...parts: string[]) =>
  readFileSync(path.join(webRoot, ...parts), "utf8");

test("npm build routes through the generated-file wrapper", () => {
  const scripts = JSON.parse(read("package.json")).scripts as Record<
    string,
    string
  >;
  assert.equal(scripts.build, "node ./scripts/build.mjs");
});

test("the build wrapper restores every generated checked-in input", () => {
  const source = read("scripts", "build.mjs");
  for (const name of ["next-env.d.ts", "tsconfig.json"]) {
    assert.match(
      source,
      new RegExp(`path\\.join\\(webRoot, "${name}"\\)`),
      `wrapper must snapshot ${name}`,
    );
  }
  assert.match(
    source,
    /restoreAll\(snapshots\)/,
    "wrapper must restore snapshots",
  );
  assert.match(
    source,
    /stdio: "inherit"/,
    "wrapper must preserve Next build diagnostics",
  );
});

test("the build wrapper makes the standalone output self-contained", () => {
  const source = read("scripts", "build.mjs");
  assert.match(source, /function completeStandaloneBundle\(\)/);
  assert.match(source, /path\.join\(standaloneDir, "\.next", "static"\)/);
  assert.match(source, /path\.join\(standaloneDir, "public"\)/);
  assert.match(source, /if \(status === 0\) completeStandaloneBundle\(\)/);
});
