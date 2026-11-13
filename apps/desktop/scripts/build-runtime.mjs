import { cp, mkdir, rm, readFile, writeFile, readdir } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { sha256 } from '../src/bundles.mjs';
import { systemTar } from '../src/platform.mjs';
import { appRoot, loadTarget } from './lib/target.mjs';

// Finder and Spotlight may write .DS_Store into a folder while it is being removed.
const clear = folder => rm(folder, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });

// Usage: node scripts/build-runtime.mjs [--target macos-arm64|macos-x64|windows-x64] [--assemble] [--new-key]
const target = await loadTarget();
const WINDOWS = target.platform === 'win32';
// Builds from the committed HEAD of the DeepTutor checkout this app lives in.
const source = path.resolve(process.env.DEEPTUTOR_SOURCE || path.join(appRoot, '../..'));
const build = path.join(target.local, 'build');
const runtime = target.runtime;
const pythonDirectory = path.join(target.local, 'python-downloads', target.python.build);
const python = path.join(pythonDirectory, WINDOWS ? 'python.exe' : `bin/python${target.python.version.split('.').slice(0, 2).join('.')}`);
const nodeArchive = path.join(target.local, target.node.file);
const run = (command, args, options = {}) => execFileSync(command, args, { stdio: 'inherit', ...options });
const npm = (args, cwd) => run(target.nodeBin, [target.npmCli, ...args], { cwd, env: {
  ...process.env, PATH: [path.dirname(target.nodeBin), process.env.PATH].join(path.delimiter),
  NEXT_PUBLIC_API_BASE: '__NEXT_PUBLIC_API_BASE_PLACEHOLDER__',
  NEXT_PUBLIC_AUTH_ENABLED: '__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__', NEXT_TELEMETRY_DISABLED: '1',
} });
const assembleOnly = process.argv.includes('--assemble');
console.log(`Building the ${target.id} core bundle`);

async function fetchNode() {
  try { if (await sha256(nodeArchive) === target.node.sha256) return; }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const response = await fetch(`https://nodejs.org/dist/v${target.node.version}/${target.node.file}`);
  if (!response.ok) throw new Error(`Node download failed: ${response.status}`);
  await pipeline(Readable.fromWeb(response.body), createWriteStream(nodeArchive));
}

await mkdir(target.local, { recursive: true });
if (!assembleOnly) {
  await fetchNode();
  if (await sha256(nodeArchive) !== target.node.sha256) throw new Error('Node runtime checksum mismatch');
  await clear(path.join(target.local, 'node'));
  await mkdir(path.join(target.local, 'node'));
  run(systemTar(), ['-xf', nodeArchive, '-C', path.join(target.local, 'node'), '--strip-components', '1']);

  const commit = execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  await clear(build);
  await mkdir(build, { recursive: true });
  run('git', ['-C', source, 'archive', '--output', path.join(target.local, 'source.tar'), commit]);
  run(systemTar(), ['-xf', path.join(target.local, 'source.tar'), '-C', build]);
  await writeFile(path.join(build, 'BUILD_COMMIT'), commit + '\n');
  run('uv', ['python', 'install', target.python.build, '--install-dir', path.join(target.local, 'python-downloads'), '--no-bin']);
  run('uv', ['pip', 'install', '--break-system-packages', '--python', python, ...(target.pip ?? []), '-r', path.join(build, 'requirements/full.txt')]);
  npm(['ci', '--legacy-peer-deps'], path.join(build, 'web'));
  npm(['run', 'build'], path.join(build, 'web'));
}
if (await sha256(nodeArchive) !== target.node.sha256) throw new Error('Node runtime checksum mismatch');
await clear(runtime);
await mkdir(path.join(runtime, 'core'), { recursive: true });
for (const name of ['deeptutor', 'deeptutor_cli', 'assets', 'scripts', 'requirements', 'pyproject.toml', 'build_metadata.py', 'build_support.py', 'setup.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md']) {
  await cp(path.join(build, name), path.join(runtime, 'core', name), {
    recursive: true, filter: file => !file.split(path.sep).includes('__pycache__'),
  });
}
await cp(pythonDirectory, path.join(runtime, 'python'), { recursive: true, verbatimSymlinks: true });
// Wheel-generated console scripts otherwise retain the builder's absolute path.
// Windows launchers are .exe files; the runtime only ever calls python -m.
if (!WINDOWS) {
  for (const entry of await readdir(path.join(runtime, 'python/bin'), { withFileTypes: true })) {
    if (!entry.isFile()) continue;
    const file = path.join(runtime, 'python/bin', entry.name);
    const bytes = await readFile(file);
    if (bytes.subarray(0, 2).toString() !== '#!') continue;
    const text = bytes.toString('utf8');
    if (!/^#![^\n]*python[^\n]*\n/.test(text)) continue;
    const launcher = '#!/bin/sh\n\'\'\'exec\' "$(dirname "$0")/python3.12" "$0" "$@"\n\' \'\'\'\n';
    await writeFile(file, text.replace(/^#![^\n]*\n/, launcher));
  }
}
await cp(path.join(target.local, 'node'), path.join(runtime, 'node'), { recursive: true, verbatimSymlinks: true });
await cp(path.join(build, 'web/.next/standalone'), path.join(runtime, 'web'), { recursive: true, verbatimSymlinks: true });
await cp(path.join(build, 'BUILD_COMMIT'), path.join(runtime, 'BUILD_COMMIT'));
const freeze = execFileSync('uv', ['pip', 'freeze', '--python', python], { encoding: 'utf8' });
await writeFile(path.join(runtime, 'PYTHON_DEPENDENCIES.txt'), freeze);
await writeFile(path.join(runtime, 'BUILD_INFO.json'), JSON.stringify({
  target: target.id, coreCommit: (await readFile(path.join(build, 'BUILD_COMMIT'), 'utf8')).trim(),
  python: target.python.version, node: target.node.version, platform: target.platform, arch: target.arch,
}, null, 2));
// --new-key passes through for throwaway builds, such as pull requests without the release key.
run(process.execPath, [path.join(appRoot, 'scripts/seal-runtime.mjs'), '--target', target.id,
  ...process.argv.filter(arg => arg === '--new-key')]);
