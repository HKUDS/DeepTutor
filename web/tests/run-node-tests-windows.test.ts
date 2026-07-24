import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const runnerPath = path.resolve(process.cwd(), "scripts/run-node-tests.mjs");

test("node test runner launches TypeScript through the current Node runtime", () => {
  const source = readFileSync(runnerPath, "utf8");

  assert.match(source, /run\(process\.execPath/);
  assert.match(source, /"typescript", "bin", "tsc"/);
});
