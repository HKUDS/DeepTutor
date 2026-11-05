import { cp, mkdir, rm, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { appRoot } from './target.mjs';
import { verifyManifest, sha256 } from '../../src/bundles.mjs';

/** Copies the shell into .local/<id>/app with the version of the core it ships. */
export async function stageApp(target) {
  // The app is versioned with the DeepTutor core it ships.
  const seed = JSON.parse(await readFile(path.join(target.seed, 'runtime.json'), 'utf8'));
  verifyManifest(seed, await readFile(path.join(appRoot, 'assets/runtime-public.pem')), target.arch, target.platform);
  if (await sha256(path.join(target.seed, seed.archive)) !== seed.sha256) {
    throw new Error('The bundled core checksum does not match its manifest');
  }
  const version = seed.coreVersion;
  const stage = path.join(target.local, 'app');
  await rm(stage, { recursive: true, force: true });
  await mkdir(stage, { recursive: true });
  for (const name of ['src', 'assets', 'README.md']) {
    await cp(path.join(appRoot, name), path.join(stage, name), { recursive: true });
  }
  const pkg = JSON.parse(await readFile(path.join(appRoot, 'package.json'), 'utf8'));
  await writeFile(path.join(stage, 'package.json'), JSON.stringify({ ...pkg, version }, null, 2));
  await cp(path.join(appRoot, '../../LICENSE'), path.join(stage, 'LICENSE'));
  return { stage, version, pkg, out: path.join(appRoot, 'out') };
}

export const PACKAGER = {
  name: 'Open DeepTutor', appBundleId: 'org.deeptutor.open-desktop',
  overwrite: true, asar: false, prune: false,
};
