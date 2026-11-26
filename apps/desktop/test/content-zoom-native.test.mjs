import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const exec = promisify(execFile);

test('Windows content zoom changes rendered pixels and survives a cold Electron restart', {
  skip: process.platform !== 'win32' && 'requires a Windows desktop',
  timeout: 120_000,
}, async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'deeptutor-zoom-'));
  t.after(() => rm(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }));
  const { default: electron } = await import('electron');
  for (const phase of ['exercise', 'restore']) {
    const env = { ...process.env, OPEN_DEEPTUTOR_ZOOM_TEST_ROOT: root, OPEN_DEEPTUTOR_ZOOM_TEST_PHASE: phase };
    delete env.ELECTRON_RUN_AS_NODE;
    try {
      await exec(electron, [fileURLToPath(new URL('./fixtures/content-zoom-native.mjs', import.meta.url))], {
        env, timeout: 55_000, maxBuffer: 1024 * 1024,
      });
    } catch (error) {
      assert.fail(`Native Electron ${phase} failed:\n${error.stdout ?? ''}\n${error.stderr ?? ''}`);
    }
    const report = JSON.parse(await readFile(path.join(root, `${phase}.json`), 'utf8'));
    assert.ok(report.measurements.length > 0);
    t.diagnostic(JSON.stringify(report));
  }
  assert.deepEqual(JSON.parse(await readFile(path.join(root, 'content-zoom.json'), 'utf8')), { factor: 1.25 });
});
