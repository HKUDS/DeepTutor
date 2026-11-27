import assert from 'node:assert/strict';
import { cp, mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

const FAKE_XCRUN = `#!${process.execPath}
const fs = require('node:fs');
const args = process.argv.slice(2);
fs.appendFileSync(process.env.CALLS, args.slice(0, 2).join(' ') + '\\n');
if (args[1] === 'submit') {
  // RESULT selects the fake notarytool behaviour; MODE narrows it further.
  const mode = process.env.MODE || 'normal';
  if (mode === 'stderr-failure') {
    console.error(process.env.STDERR_TEXT || 'fake notarytool diagnostic');
    process.exit(Number(process.env.EXIT_CODE || '1'));
  }
  if (mode === 'empty-zero') process.exit(0);
  if (mode === 'not-json') { console.log('not json at all'); process.exit(0); }
  console.log(JSON.stringify({id: 'fixture-id', status: process.env.RESULT}));
}
if (args[1] === 'log') fs.writeFileSync(args.at(-1), JSON.stringify({status: process.env.RESULT}));
`;

/**
 * Run the real notarize.mjs against a fake xcrun.
 *
 * `extraEnv` overrides the defaults, and `omitXcrun` removes the tool from PATH
 * entirely so the spawn itself fails the way a missing Command Line Tools
 * install would.
 */
async function runNotarize({ result = 'Accepted', mode = 'normal', extraEnv = {}, omitXcrun = false } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'notarization-'));
  await mkdir(path.join(root, 'scripts/lib'), { recursive: true });
  await mkdir(path.join(root, 'out'));
  await cp(new URL('../scripts/notarize.mjs', import.meta.url), path.join(root, 'scripts/notarize.mjs'));
  await writeFile(path.join(root, 'scripts/lib/target.mjs'), `export const appRoot = ${JSON.stringify(root)};\n`);
  await writeFile(path.join(root, 'out/test.dmg'), 'fixture');
  if (!omitXcrun) await writeFile(path.join(root, 'xcrun'), FAKE_XCRUN, { mode: 0o755 });

  const calls = path.join(root, 'calls');
  const env = {
    ...process.env,
    // An empty bin dir stands in for "xcrun is not installed".
    PATH: omitXcrun ? path.join(root, 'empty-bin') : root + path.delimiter + process.env.PATH,
    CALLS: calls,
    RESULT: result,
    MODE: mode,
    APPLE_ID: 'fixture@example.test',
    APPLE_TEAM_ID: 'fixture-team',
    APPLE_APP_PASSWORD: 'secret-fixture',
    ...extraEnv,
  };
  if (omitXcrun) await mkdir(env.PATH, { recursive: true });

  const run = spawnSync(process.execPath, [path.join(root, 'scripts', 'notarize.mjs')], { encoding: 'utf8', env });
  const read = async name => {
    try { return await readFile(path.join(root, 'out', name), 'utf8'); } catch { return null; }
  };
  const callList = async () => {
    try { return await readFile(calls, 'utf8'); } catch { return ''; }
  };
  return {
    root, run, read, callList,
    cleanup: () => rm(root, { recursive: true, force: true }),
  };
}

// Exercise the actual CLI with a fake Apple tool: Invalid still exits zero.
// Rejected submissions must keep a report and must never reach stapler.
for (const status of ['Invalid', 'Accepted']) {
  test(`notarization handles Apple's ${status} result`, { skip: process.platform === 'win32' }, async () => {
    const h = await runNotarize({ result: status });
    try {
      assert.equal(h.run.status, status === 'Accepted' ? 0 : 1);
      const calls = await h.callList();
      assert.equal(calls.includes('stapler staple'), status === 'Accepted');
      assert.equal(calls.includes('stapler validate'), status === 'Accepted');
      assert.equal(JSON.parse(await h.read('notarization-log.json')).status, status);
      assert.equal((h.run.stdout + h.run.stderr).includes('secret-fixture'), false);
      // A handshake that worked must not leave an error artifact behind.
      assert.equal(await h.read('notarization-submission.error.json'), null);
    } finally { await h.cleanup(); }
  });
}

// #2714: notarytool writes most submission failures to stderr, which the script
// used to discard, leaving an empty {} artifact and an unexplained error.
test('a stderr-only submission failure is recorded and explained', { skip: process.platform === 'win32' }, async () => {
  const h = await runNotarize({
    mode: 'stderr-failure',
    extraEnv: { STDERR_TEXT: 'Error: HTTP status code: 401. Invalid credentials.', EXIT_CODE: '1' },
  });
  try {
    assert.equal(h.run.status, 1);
    assert.match(h.run.stderr, /Apple notarization submission failed/);
    // The reason must reach the log, not only the artifact.
    assert.match(h.run.stderr, /notarytool exited with status 1/);
    assert.match(h.run.stderr, /401\. Invalid credentials\./);

    const error = JSON.parse(await h.read('notarization-submission.error.json'));
    assert.equal(error.stage, 'submit');
    assert.equal(error.exitCode, 1);
    assert.match(error.stderr, /401/);

    // The pre-existing artifact keeps its shape: stdout was empty, so {}.
    assert.equal(await h.read('notarization-submission.json'), '{}');
    assert.equal((await h.callList()).includes('stapler'), false);
  } finally { await h.cleanup(); }
});

test('a zero exit with no output is distinguished from a non-zero exit', { skip: process.platform === 'win32' }, async () => {
  const h = await runNotarize({ mode: 'empty-zero' });
  try {
    assert.equal(h.run.status, 1);
    assert.match(h.run.stderr, /printed no result/);
    assert.doesNotMatch(h.run.stderr, /exited with status/);
    assert.equal(JSON.parse(await h.read('notarization-submission.error.json')).exitCode, 0);
  } finally { await h.cleanup(); }
});

test('unparsable output is reported as invalid JSON', { skip: process.platform === 'win32' }, async () => {
  const h = await runNotarize({ mode: 'not-json' });
  try {
    assert.equal(h.run.status, 1);
    assert.match(h.run.stderr, /not JSON/);
    const error = JSON.parse(await h.read('notarization-submission.error.json'));
    assert.match(error.stdout, /not json at all/);
  } finally { await h.cleanup(); }
});

test('a missing xcrun is reported as a spawn failure, not a submission failure', { skip: process.platform === 'win32' }, async () => {
  const h = await runNotarize({ omitXcrun: true });
  try {
    assert.equal(h.run.status, 1);
    assert.match(h.run.stderr, /could not start xcrun/);
    const error = JSON.parse(await h.read('notarization-submission.error.json'));
    assert.match(String(error.spawnError), /ENOENT/);
  } finally { await h.cleanup(); }
});

test('the diagnostic artifacts never contain the Apple credentials', { skip: process.platform === 'win32' }, async () => {
  // Force the account and password into notarytool's own output to prove the
  // redaction, not just the absence of an echo.
  const h = await runNotarize({
    mode: 'stderr-failure',
    extraEnv: {
      STDERR_TEXT: 'Error: 401 for fixture@example.test with secret-fixture',
      EXIT_CODE: '1',
    },
  });
  try {
    const error = await h.read('notarization-submission.error.json');
    assert.match(error, /\[redacted\]/);
    assert.equal(error.includes('secret-fixture'), false);
    assert.equal(error.includes('fixture@example.test'), false);
    assert.equal((h.run.stdout + h.run.stderr).includes('secret-fixture'), false);
  } finally { await h.cleanup(); }
});
