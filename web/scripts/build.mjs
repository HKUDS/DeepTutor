#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { cpSync, existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { configureTypeIncludes } from "./next-type-includes.mjs";
import { copyPdfjsAssets } from "./copy-pdfjs-assets.mjs";

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

function prepareBuildTsconfig(snapshots, distDir) {
  const tsconfigPath = path.join(webRoot, "tsconfig.json");
  const tsconfig = snapshots.find(([filePath]) => filePath === tsconfigPath);
  if (!tsconfig) return null;
  const buildTsconfigPath = path.join(
    webRoot,
    `tsconfig.deeptutor-build-${process.pid}.json`,
  );
  restore(buildTsconfigPath, configureTypeIncludes(tsconfig[1], distDir));
  return buildTsconfigPath;
}

export function packageStandaloneAssets(sourceRoot, distDir) {
  const distRoot = path.resolve(sourceRoot, distDir);
  const standaloneRoot = path.join(distRoot, "standalone");
  const server = path.join(standaloneRoot, "server.js");
  const staticAssets = path.join(distRoot, "static");
  if (!existsSync(server) || !existsSync(staticAssets)) {
    throw new Error(
      `Next build did not produce a complete standalone bundle in ${distRoot}`,
    );
  }

  // Next omits these runtime assets from standalone output (#1424). Keep the
  // active dist directory name so server.js can resolve its own client chunks.
  const standaloneStatic = path.join(standaloneRoot, distDir, "static");
  rmSync(standaloneStatic, { recursive: true, force: true });
  cpSync(staticAssets, standaloneStatic, { recursive: true });

  const publicAssets = path.join(sourceRoot, "public");
  if (existsSync(publicAssets)) {
    const standalonePublic = path.join(standaloneRoot, "public");
    rmSync(standalonePublic, { recursive: true, force: true });
    cpSync(publicAssets, standalonePublic, { recursive: true });
  }
}

const snapshots = generatedPaths
  .filter((path) => process.env.DEEPTUTOR_BUILD_SKIP_MISSING !== "1")
  .map((path) => [path, snapshot(path)]);

const isEntry =
  import.meta.url === pathToFileURL(process.argv[1] ?? "").href;

export { restoreAll };

if (isEntry) {
  const distDir = process.env.DEEPTUTOR_NEXT_DIST_DIR || ".next";
  const buildTsconfigPath = prepareBuildTsconfig(snapshots, distDir);
  const isVercel = process.env.VERCEL === "1";
  let result;
  try {
    copyPdfjsAssets();
    // On Vercel (process.env.VERCEL === "1") do NOT force --webpack: the
    // post-build validator expects Turbopack's output layout and fails with
    // ENOENT routes-manifest-deterministic.json otherwise (see issue #1428).
    // Local and Docker builds use the Webpack standalone runtime; Vercel
    // packages its own deployment output.
    const args = isVercel
      ? [nextBin, "build", ...process.argv.slice(2)]
      : [nextBin, "build", "--webpack", ...process.argv.slice(2)];
    result = spawnSync(
      process.execPath,
      args,
      {
        cwd: webRoot,
        stdio: "inherit",
        env: {
          ...process.env,
          ...(buildTsconfigPath
            ? { DEEPTUTOR_NEXT_TSCONFIG: path.basename(buildTsconfigPath) }
            : {}),
        },
      },
    );
  } finally {
    if (buildTsconfigPath) rmSync(buildTsconfigPath, { force: true });
    restoreAll(snapshots);
  }
  if (result.error) {
    console.error(result.error);
    process.exit(1);
  }
  const status = result.status ?? 1;
  if (status === 0 && !isVercel) packageStandaloneAssets(webRoot, distDir);
  process.exit(status);
}
