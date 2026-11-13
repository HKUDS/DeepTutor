import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import http from 'node:http';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { localURL, externalURL, validateConfig } from '../src/config.mjs';
import { canonicalManifest, verifyManifest, installBundle, sha256 } from '../src/bundles.mjs';
import { runtimeLayout, systemTar } from '../src/platform.mjs';
import { ProcessGroup, availablePort, probe, waitReady } from '../src/processes.mjs';
import { SourceRuntime, stageBundledWeb } from '../src/runtime.mjs';

test('only explicit loopback origins are accepted for attachment', () => {
  assert.equal(localURL('http://127.0.0.1:3782/'), 'http://127.0.0.1:3782');
  for (const url of ['https://example.com', 'http://localhost.attacker.com', 'http://user@localhost:80', 'file:///tmp/test', 'http://localhost/?token=foo']) {
    assert.throws(() => localURL(url));
  }
  assert.equal(externalURL('file:///etc/passwd'), false);
  assert.equal(externalURL('https://deeptutor.info/'), true);
});

test('source data cannot share the checkout', () => {
  const config = { schemaVersion: 1, mode: 'source', sourcePath: '/tmp/core', pythonPath: '/python', nodePath: '/node', runtimeHome: '/tmp/core/data' };
  assert.throws(() => validateConfig(config));
  assert.equal(validateConfig({ ...config, runtimeHome: '/tmp/data' }).runtimeHome, path.resolve('/tmp/data'));
});

test('update signatures bind version, checksum and architecture', () => {
  const { privateKey, publicKey } = generateKeyPairSync('ed25519');
  const manifest = { formatVersion: 1, protocolVersion: 1, platform: process.platform, arch: 'arm64', runtimeId: '1.7.0-test-arm64', archive: 'core.tar.gz', sha256: 'a'.repeat(64) };
  manifest.signature = sign(null, Buffer.from(canonicalManifest(manifest)), privateKey).toString('base64');
  assert.equal(verifyManifest(manifest, publicKey, 'arm64'), manifest);
  assert.throws(() => verifyManifest({ ...manifest, sha256: 'b'.repeat(64) }, publicKey, 'arm64'));
  assert.throws(() => verifyManifest(manifest, publicKey, 'x64'));
  assert.throws(() => verifyManifest({ ...manifest, runtimeId: '../outside' }, publicKey, 'arm64'));
  assert.throws(() => verifyManifest({ ...manifest, archive: '../core.tar.gz' }, publicKey, 'arm64'));
});

test('occupied ports are left alone and an available port is chosen', async t => {
  const server = http.createServer((_req, res) => res.end('ready'));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const occupied = server.address().port;
  assert.notEqual(await availablePort(occupied), occupied);
  assert.equal(await probe(`http://127.0.0.1:${occupied}`), true);
});

test('a signed bundle installs from and into paths containing spaces and Chinese characters', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'DeepTutor 安装 test '));
  t.after(() => rm(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }));
  const source = path.join(root, 'source');
  const seed = path.join(root, 'seed');
  await mkdir(seed, { recursive: true });
  const layout = runtimeLayout();
  for (const relative of [layout.python, layout.node, 'core/deeptutor_cli/main.py', 'web/server.js']) {
    const file = path.join(source, relative);
    await mkdir(path.dirname(file), { recursive: true });
    await writeFile(file, 'test runtime file');
  }
  // Keep tar's arguments ASCII; the regression is in the installer's paths.
  execFileSync(systemTar(), ['-czf', '../seed/core.tar.gz', '.'], { cwd: source });
  const { privateKey, publicKey } = generateKeyPairSync('ed25519');
  const manifest = {
    formatVersion: 1, protocolVersion: 1, platform: process.platform, arch: process.arch,
    runtimeId: 'test-unicode', archive: 'core.tar.gz', sha256: await sha256(path.join(seed, 'core.tar.gz')),
  };
  manifest.signature = sign(null, Buffer.from(canonicalManifest(manifest)), privateKey).toString('base64');
  const manifestFile = path.join(seed, 'runtime.json');
  await writeFile(manifestFile, JSON.stringify(manifest));
  const installed = await installBundle(manifestFile, path.join(root, '用户 data'), publicKey);
  assert.equal(await readFile(path.join(installed.destination, layout.python), 'utf8'), 'test runtime file');
  assert.deepEqual((await installBundle(manifestFile, path.join(root, '用户 data'), publicKey)).manifest, manifest);
});

test('stopping attach mode never stops the attached server', async t => {
  const server = http.createServer((_req, res) => res.end('ready'));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const url = `http://127.0.0.1:${server.address().port}`;
  const runtime = new SourceRuntime();
  await runtime.start({ schemaVersion: 1, mode: 'attach', url }, '/unused');
  assert.equal(runtime.state.phase, 'ready');
  await runtime.stop();
  assert.equal(await probe(url), true);
});

test('process owner terminates a real child and rejects nonzero commands', async () => {
  const group = new ProcessGroup();
  await assert.rejects(group.run(process.execPath, ['-e', 'process.exit(7)']), /7/);
  const port = await availablePort();
  const child = group.spawn(process.execPath, ['-e', `require('http').createServer((q,s)=>s.end('ok')).listen(${port},'127.0.0.1')`]);
  await waitReady(`http://127.0.0.1:${port}`, { timeout: 5000 });
  await group.stop();
  assert.equal(group.alive(child), false);
  assert.equal(await probe(`http://127.0.0.1:${port}`), false);
});

test('readiness polling can be cancelled', async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(waitReady('http://127.0.0.1:1', { signal: controller.signal }), /abort/i);
});

test('public placeholders are patched in a cache, preserving immutable bundle', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'Open DeepTutor test '));
  t.after(() => rm(root, { recursive: true, force: true }));
  const source = path.join(root, 'source');
  await mkdir(path.join(source, '.next/static'), { recursive: true });
  const contents = '__NEXT_PUBLIC_API_BASE_PLACEHOLDER__ __NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__';
  await writeFile(path.join(source, 'server.js'), contents);
  await writeFile(path.join(source, '.next/static/client.js'), contents);
  const cache = await stageBundledWeb(source, path.join(root, 'cache'), 'http://127.0.0.1:1001', 'false');
  assert.equal(await readFile(path.join(cache, 'server.js'), 'utf8'), 'http://127.0.0.1:1001 false');
  assert.equal(await readFile(path.join(source, 'server.js'), 'utf8'), contents);
  await stageBundledWeb(source, path.join(root, 'cache'), 'http://127.0.0.1:1002', 'true');
  assert.equal(await readFile(path.join(cache, '.next/static/client.js'), 'utf8'), 'http://127.0.0.1:1002 true');
});
