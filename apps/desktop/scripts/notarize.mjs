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
// Capture output instead of throwing execFile errors containing secret arguments.
const submit = spawnSync('xcrun', ['notarytool', 'submit', dmg, ...auth, '--wait', '--output-format', 'json'], { encoding: 'utf8' });
await writeFile(path.join(out, 'notarization-submission.json'), submit.stdout || '{}');
let result;
try { result = JSON.parse(submit.stdout); }
catch { throw new Error('Apple returned no notarization result; check the submission artifact'); }
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
