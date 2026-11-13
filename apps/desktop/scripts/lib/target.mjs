import path from 'node:path';
import { readdir } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { runtimeLayout, targetId } from '../../src/platform.mjs';

export const appRoot = fileURLToPath(new URL('../..', import.meta.url));
const platforms = path.join(appRoot, 'platforms');

/**
 * The build target from `--target <id>` or OPEN_DEEPTUTOR_TARGET, defaulting to
 * this computer. Every file of a target's build lives under .local/<id>/.
 */
export async function loadTarget(argv = process.argv) {
  const flag = argv.indexOf('--target');
  const id = (flag >= 0 ? argv[flag + 1] : undefined) ?? process.env.OPEN_DEEPTUTOR_TARGET ?? targetId();
  const known = (await readdir(platforms, { withFileTypes: true })).filter(entry => entry.isDirectory()).map(entry => entry.name);
  if (!known.includes(id)) throw new Error(`Unknown target ${id}; expected one of ${known.join(', ')}`);
  const target = (await import(pathToFileURL(path.join(platforms, id, 'target.mjs')).href)).default;
  if (target.platform !== process.platform) throw new Error(`${id} must be built on ${target.platform === 'win32' ? 'Windows' : 'macOS'}`);
  // Apple Silicon runs the x64 toolchain through Rosetta; nothing runs arm64 code on Intel.
  const rosetta = target.platform === 'darwin' && target.arch === 'x64' && process.arch === 'arm64';
  if (target.arch !== process.arch && !rosetta) throw new Error(`${id} cannot be built on ${targetId()}`);
  const local = path.join(appRoot, '.local', id);
  const layout = runtimeLayout(target.platform);
  return {
    ...target, folder: path.join(platforms, id), local, layout,
    seed: path.join(local, 'seed'),
    runtime: path.join(local, 'runtime'),
    // The target's own Node runs every build step, so native packages match its architecture.
    nodeBin: path.join(local, layout.node),
    npmCli: path.join(local, layout.npm),
  };
}
