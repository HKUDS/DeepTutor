#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { removeNextTypeIncludes } from "./next-type-includes.mjs";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const tsconfigPath = path.join(webRoot, "tsconfig.json");
const tscBin = path.join(
  webRoot,
  "node_modules",
  "typescript",
  "bin",
  "tsc",
);
const original = readFileSync(tsconfigPath, "utf8");
const isolatedTsconfigPath = path.join(
  webRoot,
  `tsconfig.deeptutor-typecheck-${process.pid}.json`,
);

let result;
try {
  writeFileSync(
    isolatedTsconfigPath,
    removeNextTypeIncludes(original),
    "utf8",
  );
  result = spawnSync(
    process.execPath,
    [
      tscBin,
      "-p",
      isolatedTsconfigPath,
      "--noEmit",
      "--incremental",
      "false",
    ],
    { cwd: webRoot, stdio: "inherit" },
  );
} finally {
  rmSync(isolatedTsconfigPath, { force: true });
}

if (result.error) {
  console.error(result.error);
  process.exit(1);
}
process.exit(result.status ?? 1);
