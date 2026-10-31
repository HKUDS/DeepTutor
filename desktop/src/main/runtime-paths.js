'use strict';

/**
 * Where the shell finds DeepTutor on disk.
 *
 * Three deployment shapes are supported, in priority order:
 *   1. packaged  — an install that ships `resources/web` (Next standalone) and
 *                  optionally `resources/backend` (a frozen server binary).
 *   2. checkout  — this repository, with `web/.next-deeptutor/standalone`.
 *   3. fallback  — the checkout's dev server (`npm run dev`) while iterating.
 */

const fs = require('node:fs');
const path = require('node:path');

const IS_WINDOWS = process.platform === 'win32';
const SERVER_ENTRY = 'server.js';

function exists(target) {
  try {
    fs.accessSync(target);
    return true;
  } catch {
    return false;
  }
}

function isDir(target) {
  try {
    return fs.statSync(target).isDirectory();
  } catch {
    return false;
  }
}

/** A Next standalone bundle is only usable if server.js and its build id exist. */
function isUsableStandalone(dir) {
  if (!dir || !isDir(dir)) return false;
  if (!exists(path.join(dir, SERVER_ENTRY))) return false;
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return false;
  }
  return entries.some((entry) => {
    if (!entry.isDirectory()) return false;
    return exists(path.join(dir, entry.name, 'BUILD_ID'));
  });
}

function firstExistingFile(candidates) {
  for (const candidate of candidates) {
    if (candidate && exists(candidate)) return candidate;
  }
  return null;
}

class RuntimePaths {
  constructor({ app, config, logger }) {
    this.app = app;
    this.config = config;
    this.logger = logger?.scope ? logger.scope('paths') : null;
    this.repoRoot = path.resolve(__dirname, '..', '..', '..');
  }

  get isPackaged() {
    return this.app.isPackaged;
  }

  get resourcesPath() {
    return process.resourcesPath || path.join(path.dirname(this.app.getPath('exe')), 'resources');
  }

  /** The DeepTutor workspace root (contains `web/`, `data/`, `deeptutor/`). */
  home() {
    const configured = this.config.get('service.home');
    if (configured && isDir(configured)) return configured;
    if (configured) this.logger?.warn(`configured home does not exist: ${configured}`);

    const fromEnv = (process.env.DEEPTUTOR_HOME || '').trim();
    if (fromEnv && isDir(fromEnv)) return fromEnv;

    if (this.isPackaged) {
      const bundled = path.join(this.resourcesPath, 'deeptutor');
      if (isDir(bundled)) return bundled;
      return path.join(this.app.getPath('userData'), 'home');
    }
    return this.repoRoot;
  }

  /** Python interpreter able to `import deeptutor`. */
  python() {
    const configured = this.config.get('service.pythonPath');
    if (configured && exists(configured)) return { command: configured, source: 'config' };

    const fromEnv = (process.env.DEEPTUTOR_PYTHON || '').trim();
    if (fromEnv && exists(fromEnv)) return { command: fromEnv, source: 'env' };

    const home = this.home();
    const venv = this.isPackaged ? null : firstExistingFile([
      path.join(home, '.venv', 'Scripts', 'python.exe'),
      path.join(home, '.venv', 'bin', 'python'),
      path.join(home, 'venv', 'Scripts', 'python.exe'),
      path.join(home, 'venv', 'bin', 'python'),
    ]);
    if (venv) return { command: venv, source: 'venv' };

    return { command: IS_WINDOWS ? 'python' : 'python3', source: 'path' };
  }

  /** Frozen backend binary, if the installer shipped one. */
  bundledBackend() {
    const dir = path.join(this.resourcesPath, 'backend');
    const candidate = firstExistingFile([
      path.join(dir, 'deeptutor-server.exe'),
      path.join(dir, 'deeptutor-server'),
    ]);
    return candidate ? { command: candidate, args: [], source: 'bundled' } : null;
  }

  /**
   * Node runtime for the Next server. In a packaged app there is no system
   * Node, but the Electron binary can behave as plain Node when
   * ELECTRON_RUN_AS_NODE is set — that keeps the installer free of a second
   * runtime download.
   */
  nodeRuntime() {
    const fromEnv = (process.env.DEEPTUTOR_NODE || '').trim();
    if (fromEnv && exists(fromEnv)) {
      return { command: fromEnv, env: {}, source: 'env' };
    }
    return {
      command: process.execPath,
      env: { ELECTRON_RUN_AS_NODE: '1' },
      source: 'electron',
    };
  }

  /** Candidate directories holding a runnable Next standalone server. */
  webBundles() {
    const home = this.home();
    const candidates = [];
    if (this.isPackaged) candidates.push({ dir: path.join(this.resourcesPath, 'web'), kind: 'packaged' });
    candidates.push({ dir: path.join(home, 'web', '.next-deeptutor', 'standalone'), kind: 'source' });
    candidates.push({ dir: path.join(home, 'web', '.next', 'standalone'), kind: 'source' });
    return candidates.filter((candidate) => isUsableStandalone(candidate.dir));
  }

  /** Checkout `web/` directory — only used for the `npm run dev` fallback. */
  webSource() {
    const dir = path.join(this.home(), 'web');
    if (isDir(path.join(dir, 'node_modules'))) return dir;
    return null;
  }

  settingsDir() {
    return path.join(this.home(), 'data', 'user', 'settings');
  }

  /** Auth flag lives in the workspace settings; the frontend needs it at boot. */
  authEnabled() {
    try {
      const raw = fs.readFileSync(path.join(this.settingsDir(), 'auth.json'), 'utf8');
      const parsed = JSON.parse(raw);
      return parsed?.enabled === true;
    } catch {
      return false;
    }
  }

  describe() {
    return {
      packaged: this.isPackaged,
      repoRoot: this.repoRoot,
      home: this.home(),
      python: this.python().command,
      bundles: this.webBundles().map((bundle) => `${bundle.kind}:${bundle.dir}`),
      webSource: this.webSource(),
    };
  }
}

module.exports = { RuntimePaths, isUsableStandalone };
