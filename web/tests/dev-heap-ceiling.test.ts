import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

/**
 * `next dev` renders in a worker it spawns itself, and V8 flags in argv are not
 * inherited by child processes — so a `node --max-old-space-size=N .../next dev`
 * script silently does nothing for the process that holds the memory, and Next
 * substitutes 50% of total RAM (12GB on a 24GB machine) instead. That shipped
 * for a while and ended in `Ineffective mark-compacts near heap limit`.
 * scripts/dev.mjs is the fix: the ceiling goes through NODE_OPTIONS, which the
 * worker inherits and Next honors. Every dev launch point must route through it
 * or the override quietly comes back.
 */

// The node-test harness runs from web/ (see scripts/run-node-tests.mjs).
const webRoot = process.cwd();
const repoRoot = path.resolve(webRoot, "..");

const read = (...parts: string[]) => readFileSync(path.join(...parts), "utf8");

test("npm dev scripts route through the heap-ceiling wrapper", () => {
  const scripts = JSON.parse(read(webRoot, "package.json")).scripts as Record<
    string,
    string
  >;
  for (const name of ["dev", "dev:turbo"]) {
    const script = scripts[name];
    assert.ok(script, `package.json is missing the ${name} script`);
    assert.match(
      script,
      /scripts\/dev\.mjs/,
      `${name} must launch via scripts/dev.mjs, got: ${script}`,
    );
    assert.doesNotMatch(
      script,
      /--max-old-space-size/,
      `${name} passes the heap flag in argv, where the render worker never sees it`,
    );
  }
});

test("the container dev stage routes through the wrapper too", () => {
  // Command lines only — prose mentions of `next dev` are not launch points.
  const devFrontend = read(repoRoot, "Dockerfile")
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("#"))
    .filter(
      (line) =>
        line.includes("bin/next dev") || line.includes("scripts/dev.mjs"),
    );
  assert.ok(
    devFrontend.length > 0,
    "no dev frontend command found in Dockerfile",
  );
  for (const line of devFrontend) {
    assert.match(
      line,
      /scripts\/dev\.mjs/,
      `Dockerfile dev frontend bypasses the wrapper: ${line.trim()}`,
    );
  }
});

test("the wrapper caps the ceiling and respects an explicit NODE_OPTIONS", () => {
  const source = read(webRoot, "scripts", "dev.mjs");
  // A ceiling only helps if it is a ceiling: Next's own 50%-of-RAM rule is what
  // produced the 12GB heap, so the wrapper must clamp rather than mirror it.
  assert.match(source, /Math\.min\(/, "wrapper must clamp the computed size");
  assert.match(
    source,
    /NODE_OPTIONS/,
    "the ceiling has to travel via NODE_OPTIONS to reach the worker",
  );
  assert.match(
    source,
    /max\[-_\]old\[-_\]space\[-_\]size/,
    "wrapper must detect an inherited ceiling instead of appending a second one",
  );
  assert.match(
    source,
    /HEAP_CEILING_MB\s*=\s*4096/,
    "the fallback ceiling must preserve the original 4GB dev-server budget",
  );
});
