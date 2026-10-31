'use strict';

/**
 * Supervises the two processes DeepTutor actually needs:
 *
 *   backend  — FastAPI/uvicorn  (`deeptutor.api.main:app`, default :8001)
 *   frontend — Next.js standalone server (default :3782)
 *
 * The Electron window only ever talks HTTP to the frontend, exactly like a
 * browser would, so nothing here leaks privileges into the renderer.
 *
 * The manager also supports "attach" mode: if a DeepTutor stack is already
 * listening (started from a terminal, another window, or a previous session
 * that outlived the shell), we reuse it instead of fighting over the ports.
 */

const { EventEmitter } = require('node:events');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');

const IS_WINDOWS = process.platform === 'win32';
const POLL_INTERVAL_MS = 700;
const PROBE_TIMEOUT_MS = 3000;
/** A dev server can hold the port while it compiles the first request. */
const OCCUPIED_PORT_GRACE_MS = 25000;

const STATE = Object.freeze({
  IDLE: 'idle',
  PROBING: 'probing',
  BACKEND: 'starting-backend',
  FRONTEND: 'starting-frontend',
  READY: 'ready',
  STOPPING: 'stopping',
  ERROR: 'error',
});

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * HTTP probe that never rejects.
 * `expectJson` lets us confirm the port belongs to DeepTutor rather than to
 * some unrelated dev server that happens to hold 8001.
 */
function probe(url, { timeoutMs = PROBE_TIMEOUT_MS, expectJson = false } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };

    const request = http.get(
      url,
      { timeout: timeoutMs, headers: { accept: 'application/json, text/html;q=0.9' } },
      (response) => {
        let body = '';
        response.setEncoding('utf8');
        response.on('data', (chunk) => {
          if (body.length < 8192) body += chunk;
        });
        response.on('end', () => {
          const ok = response.statusCode >= 200 && response.statusCode < 500;
          let identity = true;
          if (expectJson) {
            try {
              const parsed = JSON.parse(body);
              identity = parsed && typeof parsed.status === 'string';
            } catch {
              identity = false;
            }
          }
          finish({
            ok: ok && identity,
            status: response.statusCode,
            headers: response.headers,
            body,
            identity,
          });
        });
        response.on('error', (error) => finish({ ok: false, status: 0, error: error.code || error.message }));
      },
    );

    request.on('timeout', () => {
      request.destroy();
      finish({ ok: false, status: 0, error: 'timeout' });
    });
    request.on('error', (error) => finish({ ok: false, status: 0, error: error.code || error.message }));
  });
}

/**
 * Plain TCP check: is something already listening? Used to distinguish "nothing
 * here yet, spawn it" from "someone holds the port but is slow to answer HTTP"
 * (a Next dev server compiling its first request looks exactly like that).
 */
function portOpen(port, { host = '127.0.0.1', timeoutMs = 900 } = {}) {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host });
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(value);
    };
    socket.setTimeout(timeoutMs);
    socket.once('connect', () => finish(true));
    socket.once('timeout', () => finish(false));
    socket.once('error', () => finish(false));
  });
}

class ServiceManager extends EventEmitter {
  constructor({ config, paths, logger }) {
    super();
    this.config = config;
    this.paths = paths;
    this.logger = logger.scope('service');
    this.state = STATE.IDLE;
    this.mode = null;
    this.message = '';
    this.url = null;
    this.backendUrl = null;
    this.children = { backend: null, frontend: null };
    this.exits = { backend: null, frontend: null };
    this.startPromise = null;
    this.starting = false;
    this.stopping = false;
    this.backendRestarts = 0;
    this.startedAt = null;
  }

  getStatus() {
    return {
      state: this.state,
      mode: this.mode,
      message: this.message,
      url: this.url,
      backendUrl: this.backendUrl,
      startedAt: this.startedAt,
      processes: {
        backend: this.#processInfo('backend'),
        frontend: this.#processInfo('frontend'),
      },
    };
  }

  #processInfo(role) {
    const child = this.children[role];
    if (!child) {
      return { running: false, pid: null, exitCode: this.exits[role] };
    }
    return {
      running: child.exitCode === null && !child.killed,
      pid: child.pid ?? null,
      exitCode: child.exitCode,
    };
  }

  #set(patch) {
    Object.assign(this, patch);
    const status = this.getStatus();
    this.logger.info(`state=${status.state}${status.message ? ` (${status.message})` : ''}`);
    this.emit('status', status);
    return status;
  }

  #port(key) {
    const value = Number(this.config.get(`service.${key}`));
    return Number.isInteger(value) && value > 0 ? value : key === 'backendPort' ? 8001 : 3782;
  }

  #baseEnv() {
    const home = this.paths.home();
    const extra = this.config.get('service.extraEnv') || {};
    return {
      ...process.env,
      ...extra,
      DEEPTUTOR_HOME: home,
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8:replace',
      PYTHONUTF8: '1',
      NEXT_TELEMETRY_DISABLED: '1',
    };
  }

  async start() {
    if (this.state === STATE.READY) return this.getStatus();
    if (this.startPromise) return this.startPromise;

    this.stopping = false;
    this.starting = true;
    this.startPromise = this.#runStart()
      .catch((error) => {
        const message = error?.message || String(error);
        this.logger.error(`start failed: ${message}`);
        this.#set({ state: STATE.ERROR, message, mode: this.mode });
        throw error;
      })
      .finally(() => {
        this.startPromise = null;
        this.starting = false;
      });

    return this.startPromise;
  }

  async #runStart() {
    const backendPort = this.#port('backendPort');
    const frontendPort = this.#port('frontendPort');
    this.backendUrl = `http://127.0.0.1:${backendPort}`;
    this.url = `http://127.0.0.1:${frontendPort}`;

    this.logger.info(`runtime: ${JSON.stringify(this.paths.describe())}`);
    // A packaged install may point at a fresh workspace; child processes need a
    // real cwd or spawn fails with ENOENT before anything is logged.
    try {
      fs.mkdirSync(this.paths.home(), { recursive: true });
    } catch (error) {
      throw new Error(`工作区目录不可用：${this.paths.home()}（${error.message}）`);
    }
    this.#set({ state: STATE.PROBING, message: '检测本地服务状态…', mode: null });

    const reuse = this.config.get('service.reuseRunning') !== false;
    const [backendProbe, frontendProbe] = await Promise.all([
      probe(`${this.backendUrl}/health`, { expectJson: true }),
      probe(this.url),
    ]);

    const backendAlreadyUp = reuse && backendProbe.ok;
    const frontendAlreadyUp = reuse && frontendProbe.ok;

    if (backendAlreadyUp && frontendAlreadyUp) {
      this.mode = 'attached';
      this.startedAt = Date.now();
      this.logger.info(`attached to running DeepTutor at ${this.url}`);
      return this.#set({ state: STATE.READY, message: '已连接到运行中的 DeepTutor', mode: 'attached' });
    }

    this.mode = 'managed';

    if (backendAlreadyUp) {
      this.logger.info('reusing backend already listening');
    } else {
      if (backendProbe.status && !backendProbe.ok) {
        this.logger.warn(`port ${backendPort} answered but is not DeepTutor — starting our own backend anyway`);
      }
      await this.#startBackend(backendPort);
    }

    if (frontendAlreadyUp) {
      this.logger.info('reusing frontend already listening');
    } else {
      await this.#startFrontend(frontendPort, backendPort);
    }

    this.startedAt = Date.now();
    return this.#set({
      state: STATE.READY,
      message: this.mode === 'attached' ? '已连接到运行中的 DeepTutor' : 'DeepTutor 已就绪',
      mode: this.mode,
    });
  }

  async #startBackend(port) {
    this.#set({ state: STATE.BACKEND, message: `正在启动后端服务 (端口 ${port})…` });

    // The port answered TCP but failed the DeepTutor identity check — either a
    // foreign program, or a DeepTutor that is still initialising. Waiting is
    // strictly better than spawning a child that can only fail to bind.
    if (await portOpen(port)) {
      this.logger.warn(`port ${port} is bound but /health did not confirm DeepTutor yet`);
      this.#set({ state: STATE.BACKEND, message: `等待已在运行的后端服务 (端口 ${port})…` });
      try {
        await this.#waitUntil(
          async () => (await probe(`http://127.0.0.1:${port}/health`, { expectJson: true })).ok,
          { timeoutMs: OCCUPIED_PORT_GRACE_MS, label: '已占用端口上的后端服务' },
        );
        this.logger.info(`backend answered on :${port} after waiting`);
        return;
      } catch {
        throw new Error(`端口 ${port} 已被其他程序占用，请修改配置里的 service.backendPort`);
      }
    }

    const attempts = [];
    const bundled = this.paths.bundledBackend();
    if (bundled) {
      attempts.push({ label: 'bundled', command: bundled.command, args: ['--host', '127.0.0.1', '--port', String(port)] });
    }
    const python = this.paths.python();
    attempts.push({
      label: `python(${python.source})`,
      command: python.command,
      args: ['-m', 'deeptutor_cli.main', 'serve', '--host', '127.0.0.1', '--port', String(port)],
    });
    attempts.push({
      label: 'uvicorn',
      command: python.command,
      args: ['-m', 'uvicorn', 'deeptutor.api.main:app', '--host', '127.0.0.1', '--port', String(port), '--no-access-log', '--no-proxy-headers'],
    });

    let lastError = null;
    for (const attempt of attempts) {
      const healthUrl = `http://127.0.0.1:${port}/health`;
      const child = this.#spawn('backend', attempt.command, attempt.args, {
        env: this.#baseEnv(),
        cwd: this.paths.home(),
      });
      if (!child) {
        lastError = new Error(`无法启动 ${attempt.label}`);
        continue;
      }

      try {
        await this.#waitUntil(
          async () => {
            if (this.#exited('backend')) {
              throw new Error(`后端进程提前退出 (code ${this.exits.backend})`);
            }
            const result = await probe(healthUrl, { expectJson: true });
            return result.ok;
          },
          { timeoutMs: this.#timeout(), label: '后端服务' },
        );
        this.logger.info(`backend ready via ${attempt.label} on :${port}`);
        return;
      } catch (error) {
        lastError = error;
        this.logger.warn(`${attempt.label} failed: ${error.message}`);
        this.#kill('backend');
        await delay(400);
      }
    }

    throw new Error(`后端服务启动失败：${lastError?.message || '未知原因'}`);
  }

  async #startFrontend(port, backendPort) {
    this.#set({ state: STATE.FRONTEND, message: `正在启动界面服务 (端口 ${port})…` });

    // The port is taken but the HTTP probe was inconclusive: most likely a
    // `next dev` that is still compiling. Waiting for it beats spawning a child
    // that cannot bind, and keeps the shell honouring "reuse what is running".
    if (await portOpen(port)) {
      this.logger.info(`port ${port} already bound — waiting for it to serve HTTP`);
      this.#set({ state: STATE.FRONTEND, message: `等待已在运行的界面服务 (端口 ${port})…` });
      try {
        await this.#waitUntil(
          async () => (await probe(this.url)).ok,
          { timeoutMs: OCCUPIED_PORT_GRACE_MS, label: '已占用端口上的界面服务' },
        );
        this.logger.info(`frontend answered on ${this.url} after waiting`);
        return;
      } catch {
        throw new Error(`端口 ${port} 已被其他程序占用，请修改配置里的 service.frontendPort`);
      }
    }

    const bundle = this.paths.webBundles()[0];
    const webSource = bundle ? null : this.paths.webSource();

    if (!bundle && !webSource) {
      throw new Error(
        '未找到可用的前端产物。请先构建界面：cd web && npm run build，或重新安装完整版本。',
      );
    }

    const backendUrl = `http://127.0.0.1:${backendPort}`;
    const authEnabled = this.paths.authEnabled();
    const commonEnv = {
      ...this.#baseEnv(),
      PORT: String(port),
      HOSTNAME: '127.0.0.1',
      FRONTEND_PORT: String(port),
      BACKEND_PORT: String(backendPort),
      DEEPTUTOR_API_BASE_URL: backendUrl,
      DEEPTUTOR_AUTH_ENABLED: authEnabled ? 'true' : 'false',
      NEXT_PUBLIC_API_BASE: backendUrl,
      NEXT_PUBLIC_AUTH_ENABLED: authEnabled ? 'true' : 'false',
    };

    if (bundle) {
      const node = this.paths.nodeRuntime();
      this.logger.info(`frontend bundle (${bundle.kind}): ${bundle.dir} via node(${node.source})`);
      this.#spawn('frontend', node.command, [path.join(bundle.dir, 'server.js')], {
        cwd: bundle.dir,
        env: { ...commonEnv, ...node.env, NODE_ENV: 'production' },
      });
    } else {
      this.logger.info(`frontend dev server from ${webSource}`);
      // `shell: true` on Windows is what makes the `npm` shim resolvable; the
      // .cmd variant cannot be spawned directly on newer Node versions.
      const npm = 'npm';
      this.#spawn('frontend', npm, ['run', 'dev', '--', '--port', String(port)], {
        cwd: webSource,
        env: { ...commonEnv, NODE_ENV: 'development' },
        shell: IS_WINDOWS,
      });
    }

    await this.#waitUntil(
      async () => {
        if (this.#exited('frontend')) {
          throw new Error(`界面进程提前退出 (code ${this.exits.frontend})`);
        }
        const result = await probe(this.url);
        return result.ok;
      },
      { timeoutMs: this.#timeout(), label: '界面服务' },
    );
    this.logger.info(`frontend ready on ${this.url}`);
  }

  #timeout() {
    const configured = Number(this.config.get('service.startTimeoutMs'));
    return Number.isFinite(configured) && configured > 0 ? configured : 180000;
  }

  async #waitUntil(check, { timeoutMs, label }) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (this.stopping) throw new Error('启动已取消');
      if (await check()) return;
      await delay(POLL_INTERVAL_MS);
    }
    throw new Error(`${label}在 ${Math.round(timeoutMs / 1000)} 秒内未就绪`);
  }

  #exited(role) {
    const child = this.children[role];
    return Boolean(child) && child.exitCode !== null;
  }

  #spawn(role, command, args, { env, cwd, shell = false }) {
    this.#kill(role);
    this.exits[role] = null;
    this.logger.info(`spawn ${role}: ${command} ${args.join(' ')}`);

    let child;
    try {
      child = spawn(command, args, {
        cwd,
        env,
        shell,
        windowsHide: true,
        detached: !IS_WINDOWS,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (error) {
      this.logger.error(`spawn ${role} threw: ${error.message}`);
      return null;
    }

    this.children[role] = child;

    child.stdout?.setEncoding('utf8');
    child.stderr?.setEncoding('utf8');
    child.stdout?.on('data', (chunk) => this.logger.child(role, chunk, 'out'));
    child.stderr?.on('data', (chunk) => this.logger.child(role, chunk, 'err'));

    child.on('error', (error) => {
      this.logger.error(`${role} process error: ${error.message}`);
      this.exits[role] = this.exits[role] ?? `error:${error.code || error.message}`;
    });

    child.on('exit', (code, signal) => {
      this.exits[role] = code;
      this.logger.warn(`${role} exited (code=${code} signal=${signal})`);
      if (this.children[role] === child) this.children[role] = null;
      this.#handleUnexpectedExit(role, code, signal);
    });

    return child;
  }

  #handleUnexpectedExit(role, code, signal) {
    if (this.stopping || this.state !== STATE.READY) return;
    // A clean 0 exit while we still expect the process is still a crash from
    // the shell's point of view: the UI is about to lose its data source.
    if (code === 0 && !signal) this.logger.warn(`${role} exited cleanly but unexpectedly`);

    if (role === 'backend' && this.mode === 'managed' && this.backendRestarts < 1) {
      this.backendRestarts += 1;
      this.logger.warn('attempting one backend auto-restart');
      this.state = STATE.BACKEND;
      this.message = '后端服务意外退出，正在尝试重启…';
      this.emit('status', this.getStatus());
      setTimeout(() => {
        if (this.stopping) return;
        this.start().catch((error) => this.logger.error(`auto-restart failed: ${error.message}`));
      }, 1500);
      return;
    }

    this.#set({
      state: STATE.ERROR,
      message: `${role === 'backend' ? '后端' : '界面'}服务已退出（code ${code ?? signal ?? '未知'}）`,
    });
  }

  #kill(role) {
    const child = this.children[role];
    this.children[role] = null;
    if (!child || child.exitCode !== null) return;
    const pid = child.pid;
    if (!pid) return;
    this.logger.info(`stopping ${role} (pid ${pid})`);
    try {
      if (IS_WINDOWS) {
        spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
      } else {
        try {
          process.kill(-pid, 'SIGTERM');
        } catch {
          child.kill('SIGTERM');
        }
        setTimeout(() => {
          if (child.exitCode === null) {
            try { process.kill(-pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); }
          }
        }, 3000).unref?.();
      }
    } catch (error) {
      this.logger.warn(`failed to stop ${role}: ${error.message}`);
    }
  }

  async stop({ silent = false } = {}) {
    this.stopping = true;
    if (!silent) this.#set({ state: STATE.STOPPING, message: '正在关闭本地服务…' });
    this.#kill('frontend');
    this.#kill('backend');
    this.backendRestarts = 0;
    await delay(300);
    this.stopping = false;
    if (silent) {
      this.state = STATE.IDLE;
      this.message = '';
      this.mode = null;
    } else {
      this.#set({ state: STATE.IDLE, message: '本地服务已停止', mode: null });
    }
  }

  async restart() {
    await this.stop({ silent: true });
    this.backendRestarts = 0;
    return this.start();
  }

  /** True when the window can be pointed at the frontend. */
  isReady() {
    return this.state === STATE.READY && Boolean(this.url);
  }
}

module.exports = { ServiceManager, STATE, probe };
