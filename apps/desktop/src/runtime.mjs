import { EventEmitter } from 'node:events';
import { access, cp, mkdir, readFile, rm, symlink, realpath, readdir, writeFile } from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { validateConfig } from './config.mjs';
import { ProcessGroup, availablePort, waitReady, probe } from './processes.mjs';
import { WINDOWS } from './platform.mjs';

const SKIP = new Set(['node_modules', 'dist', 'out', 'coverage', 'playwright-report', 'test-results', '.git']);

export async function stageBundledWeb(source, cachePath, backendURL, authEnabled) {
  const target = path.join(cachePath, 'web');
  const marker = JSON.stringify({ source, backendURL, authEnabled });
  try {
    if (await readFile(path.join(target, '.desktop-config'), 'utf8') === marker) return target;
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  await rm(target, { recursive: true, force: true });
  await cp(source, target, { recursive: true });
  async function patch(file) {
    if (!/\.(js|json|html|txt)$/.test(file)) return;
    const text = await readFile(file, 'utf8');
    const updated = text.replaceAll('__NEXT_PUBLIC_API_BASE_PLACEHOLDER__', backendURL)
      .replaceAll('__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__', authEnabled);
    if (updated !== text) await writeFile(file, updated);
  }
  async function walk(folder) {
    for (const entry of await readdir(folder, { withFileTypes: true })) {
      const filename = path.join(folder, entry.name);
      if (entry.isDirectory()) await walk(filename);
      else if (entry.isFile()) await patch(filename);
    }
  }
  await walk(path.join(target, '.next'));
  await patch(path.join(target, 'server.js'));
  await writeFile(path.join(target, '.desktop-config'), marker);
  return target;
}

export async function stageWeb(sourcePath, cachePath) {
  const source = path.join(sourcePath, 'web');
  const target = path.join(cachePath, 'web');
  await rm(target, { recursive: true, force: true });
  await mkdir(cachePath, { recursive: true });
  await cp(source, target, {
    recursive: true,
    filter: file => {
      const relative = path.relative(source, file);
      return !relative.split(path.sep).some(name => SKIP.has(name) || name.startsWith('.next')
        || name.startsWith('.env') || name.endsWith('.tsbuildinfo') || name.startsWith('tsconfig.deeptutor-'));
    },
  });
  await symlink(path.join(source, 'node_modules'), path.join(target, 'node_modules'), WINDOWS ? 'junction' : 'dir');
  // Next's version display reads this sibling file. It is a disposable runtime cache.
  await mkdir(path.join(cachePath, 'deeptutor'), { recursive: true });
  await cp(path.join(sourcePath, 'deeptutor', '__version__.py'), path.join(cachePath, 'deeptutor', '__version__.py'));
  return target;
}

export class SourceRuntime extends EventEmitter {
  constructor({ log = () => {} } = {}) {
    super();
    this.group = new ProcessGroup(log);
    this.controller = new AbortController();
    this.state = { protocolVersion: 1, phase: 'idle' };
  }

  update(state) { this.state = { ...this.state, ...state }; this.emit('status', this.state); }

  async start(input, cachePath) {
    const config = validateConfig(input);
    this.config = config;
    this.update({ phase: 'starting', step: 'checking', mode: config.mode });
    try {
      if (config.mode === 'attach') {
        await waitReady(config.url, { timeout: 10000, signal: this.controller.signal });
        this.update({ phase: 'ready', step: 'attached', url: config.url, owned: false });
        return;
      }
      for (const file of [config.pythonPath, config.nodePath]) await access(file, constants.X_OK);
      await access(path.join(config.sourcePath, 'deeptutor_cli', 'main.py'));
      if (config.mode === 'source') await access(path.join(config.sourcePath, 'web', 'node_modules', 'next', 'dist', 'bin', 'next'));
      else await access(path.join(config.webPath, 'server.js'));
      await mkdir(config.runtimeHome, { recursive: true, mode: 0o700 });
      validateConfig({ ...config, sourcePath: await realpath(config.sourcePath), runtimeHome: await realpath(config.runtimeHome) });
      const backendPort = await availablePort(18801);
      const frontendPort = await availablePort(18802);
      const backendURL = `http://127.0.0.1:${backendPort}`;
      const url = `http://127.0.0.1:${frontendPort}`;
      const env = {
        ...process.env,
        PATH: [path.dirname(config.nodePath), path.dirname(config.pythonPath), process.env.PATH].filter(Boolean).join(path.delimiter),
        PYTHONPATH: config.sourcePath,
        PYTHONUNBUFFERED: '1',
        PYTHONDONTWRITEBYTECODE: '1',
        // Windows pipes otherwise use the legacy code page. Initialization
        // prints the data path, which can contain names outside that encoding.
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
        DEEPTUTOR_HOME: config.runtimeHome,
        BACKEND_PORT: String(backendPort), FRONTEND_PORT: String(frontendPort),
      };
      // A source adapter never hands environment mutation to the core's updater.
      delete env.DEEPTUTOR_LAUNCHER_PID;
      delete env.ELECTRON_RUN_AS_NODE;
      delete env.PYTHONHOME;
      await this.group.run(config.pythonPath, ['-m', 'deeptutor_cli.main', 'init', '--non-interactive', '--home', config.runtimeHome],
        { cwd: config.runtimeHome, env });
      let auth = {};
      try { auth = JSON.parse(await readFile(path.join(config.runtimeHome, 'data/user/settings/auth.json'), 'utf8')); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
      const authEnabled = String(Boolean(auth.enabled));
      Object.assign(env, {
        AUTH_ENABLED: authEnabled, NEXT_PUBLIC_AUTH_ENABLED: authEnabled,
        DEEPTUTOR_AUTH_ENABLED: authEnabled, DEEPTUTOR_API_BASE_URL: backendURL,
        NEXT_PUBLIC_API_BASE_EXTERNAL: backendURL, NEXT_PUBLIC_API_BASE: backendURL,
      });
      this.controller.signal.throwIfAborted();
      this.update({ step: 'preparingUi', url, backendURL });
      const webPath = config.mode === 'bundled'
        ? await stageBundledWeb(config.webPath, cachePath, backendURL, authEnabled)
        : await stageWeb(config.sourcePath, cachePath);
      this.controller.signal.throwIfAborted();
      if (config.mode === 'source') await this.group.run(config.nodePath, [path.join(webPath, 'scripts/copy-pdfjs-assets.mjs')], { cwd: webPath, env });
      this.update({ step: 'startingCore' });
      this.backend = this.group.spawn(config.pythonPath,
        ['-m', 'deeptutor_cli.main', 'serve', '--host', '127.0.0.1', '--port', String(backendPort)],
        { cwd: config.runtimeHome, env });
      await waitReady(`${backendURL}/health/ready`, {
        signal: this.controller.signal, alive: () => this.group.alive(this.backend),
      });
      this.update({ step: 'openingSpace' });
      this.frontend = this.group.spawn(config.nodePath,
        config.mode === 'bundled' ? [path.join(webPath, 'server.js')]
          : [path.join(webPath, 'scripts/dev.mjs'), '--webpack', '--hostname', '127.0.0.1', '--port', String(frontendPort)],
        { cwd: webPath, env: { ...env, PORT: String(frontendPort), HOSTNAME: '127.0.0.1', DEEPTUTOR_NEXT_DIST_DIR: '.next', DEEPTUTOR_NEXT_TSCONFIG: 'tsconfig.json', NEXT_TELEMETRY_DISABLED: '1' } });
      await waitReady(url, {
        signal: this.controller.signal, timeout: 240000,
        alive: () => this.group.alive(this.frontend) && this.group.alive(this.backend),
      });
      const versionFile = await readFile(path.join(config.sourcePath, 'deeptutor/__version__.py'), 'utf8');
      const coreVersion = /__version__\s*=\s*['"]([^'"]+)/.exec(versionFile)?.[1] ?? 'dev';
      this.update({ phase: 'ready', step: 'ready', coreVersion, url, owned: true });
      for (const child of [this.backend, this.frontend]) {
        child.done.then(() => {
          if (this.state.phase === 'ready') void this.fail(new Error('A core process exited. Restart the core.'));
        });
      }
      this.monitor = setInterval(async () => {
        if (this.checking || this.state.phase !== 'ready') return;
        this.checking = true;
        try {
          this.misses = await probe(`${backendURL}/health/ready`) ? 0 : (this.misses ?? 0) + 1;
          if (this.misses >= 3 && this.state.phase === 'ready') await this.fail(new Error('The core failed three health checks in a row. Restart the core.'));
        } finally { this.checking = false; }
      }, 10000);
    } catch (error) {
      if (this.state.phase !== 'stopping' && this.state.phase !== 'stopped') await this.fail(error);
    }
  }

  async fail(error) {
    clearInterval(this.monitor);
    this.update({ phase: 'error', step: null, message: error.message });
    await this.group.stop();
  }

  async stop() {
    if (this.state.phase === 'stopped') return;
    clearInterval(this.monitor);
    this.update({ phase: 'stopping', step: 'stopping' });
    this.controller.abort();
    await this.group.stop();
    this.update({ phase: 'stopped', step: 'stopped' });
  }
}
