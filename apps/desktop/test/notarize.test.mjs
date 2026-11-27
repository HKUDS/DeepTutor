import assert from 'node:assert/strict';
import { cp, mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

// Exercise the actual CLI with a fake Apple tool: Invalid still exits zero.
// Rejected submissions must keep a report and must never reach stapler.
for (const status of ['Invalid', 'Accepted']) {
  test(`notarization handles Apple's ${status} result`, { skip: process.platform === 'win32' }, async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), 'notarization-'));
    try {
      await mkdir(path.join(root, 'scripts/lib'), { recursive: true });
      await mkdir(path.join(root, 'out'));
      await cp(new URL('../scripts/notarize.mjs', import.meta.url), path.join(root, 'scripts/notarize.mjs'));
      await writeFile(path.join(root, 'scripts/lib/target.mjs'), `export const appRoot = ${JSON.stringify(root)};\n`);
      await writeFile(path.join(root, 'out/test.dmg'), 'fixture');
      await writeFile(path.join(root, 'xcrun'), `#!${process.execPath}
const fs = require('node:fs');
const args = process.argv.slice(2);
fs.appendFileSync(process.env.CALLS, args.slice(0, 2).join(' ') + '\\n');
if (args[1] === 'submit') console.log(JSON.stringify({id: 'fixture-id', status: process.env.RESULT}));
if (args[1] === 'log') fs.writeFileSync(args.at(-1), JSON.stringify({status: process.env.RESULT}));
`, { mode: 0o755 });
      const result = spawnSync(process.execPath, [path.join(root, 'scripts/notarize.mjs')], {
        encoding: 'utf8', env: { ...process.env, PATH: root + path.delimiter + process.env.PATH,
          CALLS: path.join(root, 'calls'), RESULT: status, APPLE_ID: 'fixture',
          APPLE_TEAM_ID: 'fixture', APPLE_APP_PASSWORD: 'secret-fixture' },
      });
      assert.equal(result.status, status === 'Accepted' ? 0 : 1);
      const calls = await readFile(path.join(root, 'calls'), 'utf8');
      assert.equal(calls.includes('stapler staple'), status === 'Accepted');
      assert.equal(calls.includes('stapler validate'), status === 'Accepted');
      assert.equal(JSON.parse(await readFile(path.join(root, 'out/notarization-log.json'))).status, status);
      assert.equal((result.stdout + result.stderr).includes('secret-fixture'), false);
    } finally { await rm(root, { recursive: true, force: true }); }
  });
}
