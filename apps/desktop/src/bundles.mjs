import { createHash, verify } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readFile, mkdir, rename, rm, access, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { pipeline } from 'node:stream/promises';
import { runtimeLayout, systemTar } from './platform.mjs';

const exec = promisify(execFile);
export function canonicalManifest(manifest) {
  return JSON.stringify(Object.fromEntries(Object.entries(manifest).filter(([key]) => key !== 'signature').sort(([a], [b]) => a.localeCompare(b))));
}

export function verifyManifest(manifest, publicKey, architecture = process.arch, platform = process.platform) {
  if (!manifest || manifest.formatVersion !== 1 || manifest.protocolVersion !== 1
    || manifest.platform !== platform || manifest.arch !== architecture
    || !/^[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,100}$/.test(manifest.runtimeId)
    || !/^[a-zA-Z0-9][a-zA-Z0-9.+_-]*\.tar\.gz$/.test(manifest.archive)
    || !/^[a-f0-9]{64}$/.test(manifest.sha256)) throw new Error('This core bundle is not compatible with this app or this computer');
  if (!verify(null, Buffer.from(canonicalManifest(manifest)), publicKey, Buffer.from(manifest.signature ?? '', 'base64'))) {
    throw new Error('The core bundle signature is invalid');
  }
  return manifest;
}

export async function sha256(filename) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(filename)) hash.update(chunk);
  return hash.digest('hex');
}

export async function installBundle(manifestFile, root, publicKey, progress = () => {}) {
  const manifest = verifyManifest(JSON.parse(await readFile(manifestFile, 'utf8')), publicKey);
  const destination = path.join(root, 'runtimes', manifest.runtimeId);
  try {
    const existing = JSON.parse(await readFile(path.join(destination, 'installed.json'), 'utf8'));
    if (existing.sha256 === manifest.sha256 && existing.signature === manifest.signature) {
      await checkLayout(destination);
      return { manifest, destination };
    }
    throw new Error('A different core is already installed under this runtime ID; use a new runtime ID');
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  progress('verifying');
  const archive = path.join(path.dirname(manifestFile), manifest.archive);
  if (await sha256(archive) !== manifest.sha256) throw new Error('The core bundle checksum does not match; download it again');
  await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
  const staging = `${destination}.installing`;
  await rm(staging, { recursive: true, force: true });
  await mkdir(staging, { mode: 0o700 });
  try {
    progress('firstLaunch');
    // Only locally signed, hash-verified artifacts reach extraction.
    // Windows' system tar can mangle non-ASCII command-line paths. Node opens
    // the archive and sets the working directory using Unicode-aware OS APIs.
    const extraction = exec(systemTar(), ['-xzf', '-'], { cwd: staging, timeout: 600000, windowsHide: true });
    const [input, result] = await Promise.allSettled([
      pipeline(createReadStream(archive), extraction.child.stdin), extraction,
    ]);
    if (result.status === 'rejected') throw result.reason;
    if (input.status === 'rejected') throw input.reason;
    await checkLayout(staging);
    await writeFile(path.join(staging, 'installed.json'), JSON.stringify(manifest, null, 2));
    await rename(staging, destination);
    return { manifest, destination };
  } catch (error) {
    await rm(staging, { recursive: true, force: true });
    throw error;
  }
}

async function checkLayout(root) {
  const { python, node } = runtimeLayout();
  for (const relative of [python, node, 'core/deeptutor_cli/main.py', 'web/server.js']) {
    await access(path.join(root, relative));
  }
}

export function bundleConfig(destination, runtimeHome, runtimeId) {
  const { python, node } = runtimeLayout();
  return {
    schemaVersion: 1, mode: 'bundled', runtimeId,
    sourcePath: path.join(destination, 'core'),
    pythonPath: path.join(destination, python),
    nodePath: path.join(destination, node),
    webPath: path.join(destination, 'web'), runtimeHome,
  };
}
