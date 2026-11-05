import { createPrivateKey, generateKeyPairSync, sign } from 'node:crypto';
import { mkdir, readFile, rm, writeFile, access } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { canonicalManifest, sha256 } from '../src/bundles.mjs';
import { systemTar } from '../src/platform.mjs';
import { appRoot, loadTarget } from './lib/target.mjs';
import { assertSigningKey } from './lib/signing.mjs';
import { signMacRuntime } from './lib/macos-runtime-signing.mjs';

// One signing identity covers every platform; the manifest binds platform and architecture.
const target = await loadTarget();
const keyFile = path.join(appRoot, '.local/signing-private.pem');
const publicKeyFile = path.join(appRoot, 'assets/runtime-public.pem');
await rm(target.seed, { recursive: true, force: true });
await mkdir(target.seed, { recursive: true });
if (process.env.OPEN_DEEPTUTOR_SIGNING_KEY) {
  await writeFile(keyFile, process.env.OPEN_DEEPTUTOR_SIGNING_KEY, { mode: 0o600 });
}
try { await access(keyFile); }
catch {
  // A new key orphans every shell already shipped, so it is never implicit.
  if (!process.argv.includes('--new-key')) {
    throw new Error(`Missing ${keyFile}. Restore the release signing key, set OPEN_DEEPTUTOR_SIGNING_KEY, or pass --new-key to start a new signing identity.`);
  }
  const keys = generateKeyPairSync('ed25519');
  await writeFile(keyFile, keys.privateKey.export({ type: 'pkcs8', format: 'pem' }), { mode: 0o600 });
  await writeFile(publicKeyFile, keys.publicKey.export({ type: 'spki', format: 'pem' }));
}
const privateKey = createPrivateKey(await readFile(keyFile));
assertSigningKey(privateKey, await readFile(publicKeyFile));
const coreVersion = /__version__\s*=\s*['"]([^'"]+)/.exec(await readFile(path.join(target.runtime, 'core/deeptutor/__version__.py'), 'utf8'))[1];
const commit = (await readFile(path.join(target.runtime, 'BUILD_COMMIT'), 'utf8')).trim();
const runtimeId = `${coreVersion}-${commit.slice(0, 9)}-${target.arch}`;
const archive = `open-deeptutor-core-${runtimeId}.tar.gz`;
// Sign native code before computing the archive hash and Ed25519 signature.
if (target.platform === 'darwin') {
  await signMacRuntime(target.runtime, process.env.APPLE_SIGNING_IDENTITY,
    path.join(appRoot, 'assets/entitlements.runtime.mac.plist'));
}
execFileSync(systemTar(), ['-czf', path.join(target.seed, archive), '-C', target.runtime, '.'], { stdio: 'inherit', env: { ...process.env, COPYFILE_DISABLE: '1' } });
const manifest = {
  formatVersion: 1, protocolVersion: 1, platform: target.platform, arch: target.arch,
  runtimeId, coreVersion, commit, archive, sha256: await sha256(path.join(target.seed, archive)),
};
manifest.signature = sign(null, Buffer.from(canonicalManifest(manifest)), privateKey).toString('base64');
await writeFile(path.join(target.seed, 'runtime.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log(`Sealed ${target.id} runtime ${runtimeId}`);
