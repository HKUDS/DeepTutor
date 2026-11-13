import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { installBundle, bundleConfig } from '../src/bundles.mjs';
import { SourceRuntime } from '../src/runtime.mjs';
import { probe } from '../src/processes.mjs';
import { systemPath } from '../src/platform.mjs';
import { appRoot, loadTarget } from './lib/target.mjs';

// Usage: node scripts/smoke.mjs [--target <id>]
const target = await loadTarget();
if (target.arch !== process.arch) {
  // An Intel bundle on Apple Silicon is checked by its own x64 Node, through Rosetta.
  const result = spawnSync(target.nodeBin, [fileURLToPath(import.meta.url), '--target', target.id], { stdio: 'inherit' });
  process.exit(result.status ?? 1);
}
const home = await mkdtemp(path.join(os.tmpdir(), 'Open DeepTutor 核心 smoke '));
const log = createWriteStream(path.join(target.local, 'smoke.log'));
const runtime = new SourceRuntime({ log: chunk => log.write(chunk) });
runtime.on('status', state => console.log(`${state.phase}: ${state.step ?? state.message}`));
try {
  const publicKey = await readFile(path.join(appRoot, 'assets/runtime-public.pem'), 'utf8');
  const installed = await installBundle(path.join(target.seed, 'runtime.json'), home, publicKey, console.log);
  // Deliberately hide developer toolchains. Only bundled Python/Node are used.
  process.env.PATH = systemPath();
  await runtime.start(bundleConfig(installed.destination, path.join(home, 'workspace'), installed.manifest.runtimeId), path.join(home, 'cache'));
  assert.equal(runtime.state.phase, 'ready', runtime.state.message);
  const { url, backendURL } = runtime.state;
  assert.equal(await probe(`${backendURL}/health/ready`), true);
  const page = await fetch(url);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /DeepTutor/);
  const response = await fetch(`${url}/api/settings/ui`);
  assert.equal(response.status, 200, await response.text());
  await runtime.stop();
  assert.equal(await probe(url), false);
  assert.equal(await probe(backendURL), false);
  await writeFile(path.join(target.local, 'smoke-result.json'), JSON.stringify({ target: target.id, core: installed.manifest.runtimeId, frontend: 'passed', backend: 'passed', proxy: 'passed', shutdown: 'passed', developerPATH: 'absent' }, null, 2));
  console.log(`PASS: the ${target.id} bundled runtime boots, serves UI/API, and cleans up with no developer tools on PATH.`);
} finally {
  await runtime.stop();
  log.end();
  await rm(home, { recursive: true, force: true });
}
