#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const nextBin = path.join(
  webRoot,
  "node_modules",
  "next",
  "dist",
  "bin",
  "next",
);

// Next 16 rewrites these checked-in generated inputs when it type-checks. The
// launcher used to repair them only after `npm run build` returned; moving the
// restore here also protects direct `npm run build` invocations.
const generatedPaths = [
  path.join(webRoot, "next-env.d.ts"),
  path.join(webRoot, "tsconfig.json"),
];

function snapshot(path) {
  return readFileSync(path, "utf8");
}

function restore(path, contents) {
  writeFileSync(path, contents, "utf8");
}

function restoreAll(snapshots) {
  for (const [path, contents] of snapshots) restore(path, contents);
}

function completeStandaloneBundle() {
  const distDir = path.resolve(
    webRoot,
    process.env.DEEPTUTOR_NEXT_DIST_DIR || ".next",
  );
  const standaloneDir = path.join(distDir, "standalone");
  mkdirSync(path.join(standaloneDir, ".next"), { recursive: true });
  cpSync(path.join(distDir, "static"), path.join(standaloneDir, ".next", "static"), {
    recursive: true,
    force: true,
  });
  cpSync(path.join(webRoot, "public"), path.join(standaloneDir, "public"), {
    recursive: true,
    force: true,
  });
}

const snapshots = generatedPaths
  .filter((path) => process.env.DEEPTUTOR_BUILD_SKIP_MISSING !== "1")
  .map((path) => [path, snapshot(path)]);

const isEntry =
  import.meta.url === pathToFileURL(process.argv[1] ?? "").href;

export { completeStandaloneBundle, restoreAll };

if (isEntry) {
  const result = spawnSync(
    process.execPath,
    [nextBin, "build", ...process.argv.slice(2)],
    { cwd: webRoot, stdio: "inherit" },
  );
  restoreAll(snapshots);
  if (result.error) {
    console.error(result.error);
    process.exit(1);
  }
  const status = result.status ?? 1;
  if (status === 0) completeStandaloneBundle();
  process.exit(status);
}
