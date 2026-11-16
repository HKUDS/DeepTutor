import { readdir, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { appRoot } from './lib/target.mjs';

const out = path.join(appRoot, 'out');
const images = (await readdir(out)).filter(name => name.endsWith('.dmg'));
if (images.length !== 1) throw new Error('Expected exactly one DMG to notarize');
const dmg = path.join(out, images[0]);
const auth = ['--apple-id', process.env.APPLE_ID, '--team-id', process.env.APPLE_TEAM_ID,
  '--password', process.env.APPLE_APP_PASSWORD];
if (auth.some(value => !value)) throw new Error('Missing Apple notarization credentials');

// notarytool reports most submission failures on stderr, and can also exit zero
// without printing anything. Reading only stdout turned all of those into the
// same "no notarization result" error with an empty artifact (#2714).
const secrets = [process.env.APPLE_ID, process.env.APPLE_APP_PASSWORD].filter(Boolean);
const redact = text => secrets.reduce((acc, secret) => acc.split(secret).join('[redacted]'), String(text ?? ''));

// Capture output instead of throwing execFile errors containing secret arguments.
const submit = spawnSync('xcrun', ['notarytool', 'submit', dmg, ...auth, '--wait', '--output-format', 'json'], { encoding: 'utf8' });
const submitOut = submit.stdout ?? '';
const submitErr = submit.stderr ?? '';
// The submission artifact keeps its original shape: the raw stdout, or ``{}``.
await writeFile(path.join(out, 'notarization-submission.json'), submitOut || '{}');

// Classify why the submission produced no usable result before parsing, so each
// failure names its own cause instead of collapsing into one message.
let result;
let problem;
if (submit.error) {
  problem = `could not start xcrun (${submit.error.code ?? submit.error.message})`;
} else if (!submitOut.trim()) {
  const stderrNote = submitErr.trim()
    ? ` and reported on stderr: ${redact(submitErr.trim()).split('\n').slice(-3).join(' | ')}`
    : '';
  problem = submit.status === 0
    ? `notarytool printed no result${stderrNote}`
    : `notarytool exited with status ${submit.status} and printed no result${stderrNote}`;
} else {
  try { result = JSON.parse(submitOut); }
  catch { problem = 'notarytool printed a result that is not JSON'; }
}
if (problem) {
  // Bounded tails keep the artifact small while still carrying the reason.
  await writeFile(path.join(out, 'notarization-submission.error.json'), JSON.stringify({
    stage: 'submit', problem, exitCode: submit.status, signal: submit.signal,
    spawnError: submit.error?.code ?? null,
    stdout: redact(submitOut).slice(-4000), stderr: redact(submitErr).slice(-8000),
  }, null, 2));
  throw new Error(`Apple notarization submission failed: ${problem}; see notarization-submission.error.json`);
}
if (result.id) {
  console.log(`Apple notarization ${result.id}: ${result.status}`);
  const log = spawnSync('xcrun', ['notarytool', 'log', result.id, ...auth,
    path.join(out, 'notarization-log.json')], { encoding: 'utf8' });
  if (log.status !== 0) console.warn('Could not retrieve the notarization log');
}
// notarytool can exit zero even when Apple rejects the archive.
if (submit.status !== 0 || result.status !== 'Accepted') {
  throw new Error(`Apple notarization was not accepted (${result.status ?? 'unknown'}); see notarization-log.json`);
}
for (const action of ['staple', 'validate']) {
  const result = spawnSync('xcrun', ['stapler', action, dmg], { stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`Notarization ticket ${action} failed`);
}
