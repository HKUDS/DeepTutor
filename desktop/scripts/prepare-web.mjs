#!/usr/bin/env node
/**
 * Produces the Next.js standalone bundle that the packaged desktop app ships
 * in `resources/web`.
 *
 * `next build` does not copy `static/` or `public/` into the standalone tree
 * (DeepTutor's own `web/scripts/build.mjs` does that for the CLI launcher), so
 * this script performs the same packaging step and then verifies the result.
 * Without it the packaged app renders unstyled HTML with 404s on every chunk.
 *
 * Usage:
 *   node scripts/prepare-web.mjs            # build if needed, then package
 *   node scripts/prepare-web.mjs --reuse    # reuse an existing build
 *   node scripts/prepare-web.mjs --force    # force a fresh build
 */

import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const desktopDir = path.resolve(here, '..');
const repoRoot = path.resolve(desktopDir, '..');
const webDir = process.env.DEEPTUTOR_WEB_DIR || path.join(repoRoot, 'web');

const argv = new Set(process.argv.slice(2));
const reuse = argv.has('--reuse') && !argv.has('--force');
const distDirName = process.env.DEEPTUTOR_DIST_DIR || '.next-deeptutor';

function log(message) {
  process.stdout.write(`[prepare-web] ${message}\n`);
}

function fail(message) {
  process.stderr.write(`[prepare-web] ERROR ${message}\n`);
  process.exit(1);
}

function dirSize(target) {
  let total = 0;
  const stack = [target];
  while (stack.length) {
    const current = stack.pop();
    let entries;
    try {
      entries = readdirSync(current, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) stack.push(full);
      else {
        try { total += statSync(full).size; } catch { /* ignore */ }
      }
    }
  }
  return total;
}

function standaloneRoot() {
  return path.join(webDir, distDirName, 'standalone');
}

function hasBuildId(root) {
  if (!existsSync(root)) return false;
  try {
    return readdirSync(root, { withFileTypes: true }).some(
      (entry) => entry.isDirectory() && existsSync(path.join(root, entry.name, 'BUILD_ID')),
    );
  } catch {
    return false;
  }
}

function isUsable(root) {
  return existsSync(path.join(root, 'server.js')) && hasBuildId(root);
}

function runBuild() {
  const nextBin = path.join(webDir, 'node_modules', 'next', 'dist', 'bin', 'next');
  if (!existsSync(nextBin)) {
    fail(`未找到 Next.js 可执行文件：${nextBin}\n请先在 web 目录执行 npm ci。`);
  }
  log(`building ${webDir} (distDir=${distDirName}) — this takes a few minutes`);
  const result = spawnSync(process.execPath, [nextBin, 'build', '--webpack'], {
    cwd: webDir,
    stdio: 'inherit',
    env: {
      ...process.env,
      DEEPTUTOR_NEXT_DIST_DIR: distDirName,
      NEXT_TELEMETRY_DISABLED: '1',
    },
  });
  if (result.error) fail(result.error.message);
  if (result.status !== 0) fail(`next build 失败（exit ${result.status}）`);
}

/**
 * Copy a directory tree explicitly (mkdir + copyFile) instead of fs.cpSync:
 * predictable on Windows, and it reports which file failed instead of throwing
 * an opaque error.
 */
function copyTree(source, target) {
  mkdirSync(target, { recursive: true });
  let files = 0;
  for (const entry of readdirSync(source, { withFileTypes: true })) {
    const from = path.join(source, entry.name);
    const to = path.join(target, entry.name);
    if (entry.isDirectory()) {
      files += copyTree(from, to);
    } else if (entry.isFile()) {
      copyFileSync(from, to);
      files += 1;
    }
  }
  return files;
}

function packageAssets() {
  const distRoot = path.join(webDir, distDirName);
  const standalone = standaloneRoot();
  const staticSource = path.join(distRoot, 'static');
  if (!existsSync(staticSource)) fail(`构建产物缺少 static 目录：${staticSource}`);

  const staticTarget = path.join(standalone, distDirName, 'static');
  if (existsSync(staticTarget)) rmSync(staticTarget, { recursive: true, force: true });
  const copied = copyTree(staticSource, staticTarget);
  log(`copied ${copied} static files → ${path.relative(webDir, staticTarget)}`);

  const publicSource = path.join(webDir, 'public');
  if (existsSync(publicSource)) {
    const publicTarget = path.join(standalone, 'public');
    if (existsSync(publicTarget)) rmSync(publicTarget, { recursive: true, force: true });
    const publicFiles = copyTree(publicSource, publicTarget);
    log(`copied ${publicFiles} public files → ${path.relative(webDir, publicTarget)}`);
  }
}

function main() {
  if (!existsSync(webDir)) fail(`未找到前端目录：${webDir}`);

  const alreadyBuilt = isUsable(standaloneRoot());
  if (alreadyBuilt && reuse) {
    log(`reusing existing bundle at ${standaloneRoot()}`);
  } else if (alreadyBuilt) {
    // A previous build exists; repackaging its static assets is cheap and fixes
    // the common "chunks 404" case without a full rebuild.
    log('existing bundle found — repackaging static assets (use --force to rebuild)');
  } else {
    runBuild();
    if (!isUsable(standaloneRoot())) {
      fail('next build 未产出可用的 standalone 目录（缺少 server.js 或 BUILD_ID）');
    }
  }

  packageAssets();

  const sizeMb = (dirSize(standaloneRoot()) / (1024 * 1024)).toFixed(1);
  log(`ready: ${standaloneRoot()} (${sizeMb} MB)`);
}

main();
