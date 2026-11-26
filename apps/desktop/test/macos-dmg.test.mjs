import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, writeFileSync } from 'node:fs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createDmg } from '../scripts/lib/macos.mjs';

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'macos-dmg-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  t.mock.method(process.stderr, 'write', () => true);
  return { source: path.join(root, 'dmg stage'), output: path.join(root, 'output image.dmg') };
}

function commandError(message, extra = {}) {
  return Object.assign(new Error(`Command failed: /usr/bin/hdiutil create\n${message}`), {
    status: 1, signal: null, stdout: null, stderr: Buffer.from(`${message}\n`), ...extra,
  });
}

test('DMG creation replaces stale output and preserves the packaging arguments', async (t) => {
  const { source, output } = await fixture(t);
  await writeFile(output, 'stale image');
  await createDmg(source, output, {
    run(command, args, options) {
      assert.equal(command, '/usr/bin/hdiutil');
      assert.deepEqual(args, ['create', '-volname', 'Open DeepTutor', '-srcfolder', source, '-fs', 'APFS', '-format', 'ULFO', output]);
      assert.equal(options.env.LC_ALL, 'C');
      assert.equal(existsSync(output), false);
      writeFileSync(output, 'complete image');
    },
    sleep() { assert.fail('a successful build must not wait for a retry'); },
  });
  assert.equal(await readFile(output, 'utf8'), 'complete image');
});

test('DMG creation recovers from busy resources without retaining partial images', async (t) => {
  const { source, output } = await fixture(t);
  const delays = [];
  let attempts = 0;
  await createDmg(source, output, {
    run() {
      assert.equal(existsSync(output), false, 'a partial DMG must not block the next attempt');
      attempts += 1;
      if (attempts < 3) {
        writeFileSync(output, 'partial image');
        throw commandError('hdiutil: create failed - Resource busy');
      }
      writeFileSync(output, 'complete image');
    },
    async sleep(ms) { delays.push(ms); },
  });
  assert.equal(await readFile(output, 'utf8'), 'complete image');
  assert.equal(attempts, 3);
  assert.equal(delays.length, 2);
  assert.ok(delays[0] > 0 && delays[1] > delays[0]);
});

test('DMG creation captures busy diagnostics from a real child process', async (t) => {
  const { source, output } = await fixture(t);
  const script = `
    const fs = require('node:fs');
    const [output, counter] = process.argv.slice(1);
    const attempt = fs.existsSync(counter) ? Number(fs.readFileSync(counter, 'utf8')) + 1 : 1;
    fs.writeFileSync(counter, String(attempt));
    fs.writeFileSync(output, attempt < 3 ? 'partial image' : 'complete image');
    if (attempt < 3) {
      console.error('hdiutil: create failed - Resource busy');
      process.exit(1);
    }
  `;
  await createDmg(source, output, {
    run(_command, args, options) {
      return execFileSync(process.execPath, ['-e', script, args.at(-1), source], options);
    },
    async sleep() {},
  });
  assert.equal(await readFile(output, 'utf8'), 'complete image');
  assert.equal(await readFile(source, 'utf8'), '3');
});

test('DMG creation stops after three busy failures and removes incomplete output', async (t) => {
  const { source, output } = await fixture(t);
  const failure = commandError('hdiutil: create failed - Resource busy');
  let attempts = 0;
  let waits = 0;
  await assert.rejects(createDmg(source, output, {
    run() { attempts += 1; writeFileSync(output, 'partial image'); throw failure; },
    async sleep() { waits += 1; },
  }), error => error === failure);
  assert.equal(attempts, 3);
  assert.equal(waits, 2);
  assert.equal(existsSync(output), false);
});

for (const failure of [
  commandError('hdiutil: create failed - Permission denied'),
  commandError('hdiutil: create failed - No space left on device'),
  commandError('hdiutil: create failed - File exists'),
  commandError('a different resource reported Resource busy'),
  commandError('hdiutil: create failed - Resource busy', { status: null, signal: 'SIGTERM' }),
  Object.assign(new Error('spawnSync /usr/bin/hdiutil ENOENT'), { code: 'ENOENT' }),
]) {
  test(`DMG creation does not retry ${failure.signal || failure.stderr?.toString().trim() || failure.code}`, async (t) => {
    const { source, output } = await fixture(t);
    let attempts = 0;
    await assert.rejects(createDmg(source, output, {
      run() { attempts += 1; writeFileSync(output, 'partial image'); throw failure; },
      sleep() { assert.fail('non-transient errors must not be retried'); },
    }), error => error === failure);
    assert.equal(attempts, 1);
    assert.equal(existsSync(output), false);
  });
}
