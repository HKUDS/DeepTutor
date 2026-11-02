import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import { readdir } from 'node:fs/promises';
import { agentMarker, edition, runtimeLayout, targetId } from '../src/platform.mjs';
import { canonicalManifest, verifyManifest } from '../src/bundles.mjs';

test('each build target is named in full and in short', () => {
  assert.deepEqual(edition('darwin', 'arm64'), { full: 'Open DeepTutor for MacOS with Apple Silicon', short: 'MacOS (Apple Silicon)' });
  assert.deepEqual(edition('darwin', 'x64'), { full: 'Open DeepTutor for MacOS with Intel Silicon', short: 'MacOS (Intel)' });
  assert.deepEqual(edition('win32', 'x64'), { full: 'Open DeepTutor for Windows', short: 'Windows' });
});

test('the user agent marker carries platform and architecture for the web UI', () => {
  assert.equal(agentMarker('1.7.1', 'darwin', 'x64'), 'OpenDeepTutor/1.7.1 (macOS; x64)');
  assert.equal(agentMarker('1.7.1', 'win32', 'x64'), 'OpenDeepTutor/1.7.1 (Windows; x64)');
});

test('every platform folder is a known target with a runtime layout', async () => {
  const folders = (await readdir(new URL('../platforms', import.meta.url), { withFileTypes: true }))
    .filter(entry => entry.isDirectory()).map(entry => entry.name).sort();
  assert.deepEqual(folders, ['macos-arm64', 'macos-x64', 'windows-x64']);
  for (const folder of folders) {
    const { default: target } = await import(`../platforms/${folder}/target.mjs`);
    assert.equal(targetId(target.platform, target.arch), folder);
    assert.match(target.node.sha256, /^[a-f0-9]{64}$/);
  }
  assert.equal(runtimeLayout('win32').python, 'python/python.exe');
  assert.equal(runtimeLayout('darwin').node, 'node/bin/node');
});

test('a core bundle only installs on the platform it was built for', () => {
  const { privateKey, publicKey } = generateKeyPairSync('ed25519');
  const manifest = { formatVersion: 1, protocolVersion: 1, platform: 'win32', arch: 'x64', runtimeId: '1.7.1-test-x64', archive: 'core.tar.gz', sha256: 'a'.repeat(64) };
  manifest.signature = sign(null, Buffer.from(canonicalManifest(manifest)), privateKey).toString('base64');
  assert.equal(verifyManifest(manifest, publicKey, 'x64', 'win32'), manifest);
  assert.throws(() => verifyManifest(manifest, publicKey, 'x64', 'darwin'), /not compatible/);
});
