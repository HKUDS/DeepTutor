#!/usr/bin/env node
/**
 * Keep `desktop/package.json` in sync with `deeptutor/__version__.py`.
 *
 * The Python package owns the version; electron-builder reads it from
 * package.json. Without this step the two drift silently and the installer ends
 * up carrying a stale version.
 *
 *   node scripts/version.mjs           # check only (default), exit 1 on drift
 *   node scripts/version.mjs --write   # rewrite desktop/package.json
 */

import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const desktopDir = path.dirname(here);
const repoRoot = path.dirname(desktopDir);
const versionFile = path.join(repoRoot, 'deeptutor', '__version__.py');
const packageFile = path.join(desktopDir, 'package.json');

const write = process.argv.includes('--write');

function readSourceVersion() {
  let text;
  try {
    text = readFileSync(versionFile, 'utf8');
  } catch (error) {
    console.error(`[version] cannot read ${versionFile}: ${error.message}`);
    process.exit(2);
  }
  const match = text.match(/^__version__\s*=\s*["']([^"']+)["']/m);
  if (!match) {
    console.error(`[version] no __version__ assignment found in ${versionFile}`);
    process.exit(2);
  }
  return match[1];
}

const sourceVersion = readSourceVersion();
const pkg = JSON.parse(readFileSync(packageFile, 'utf8'));

if (pkg.version === sourceVersion) {
  console.log(`[version] desktop/package.json already at ${sourceVersion}`);
  process.exit(0);
}

if (!write) {
  console.error(
    `[version] drift: deeptutor/__version__.py is ${sourceVersion}, desktop/package.json is ${pkg.version}.` +
      ' Run `npm run version:sync` to fix.',
  );
  process.exit(1);
}

const previous = pkg.version;
pkg.version = sourceVersion;
writeFileSync(packageFile, `${JSON.stringify(pkg, null, 2)}\n`, 'utf8');
console.log(`[version] desktop/package.json ${sourceVersion} (was ${previous ?? 'unset'})`);
