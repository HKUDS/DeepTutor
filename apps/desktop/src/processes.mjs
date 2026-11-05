import { spawn, spawnSync } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { WINDOWS } from './platform.mjs';

/** Windows has no process groups or POSIX signals; taskkill ends a process and all its descendants. */
export function killTree(pid, log = () => {}) {
  const taskkill = path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'taskkill.exe');
  const result = spawnSync(taskkill, ['/PID', String(pid), '/T', '/F'], { windowsHide: true, encoding: 'utf8' });
  // 128: the process already exited.
  if (result.status !== 0 && result.status !== 128) log(`${result.stderr || result.error?.message || 'taskkill failed'}\n`);
}

export class ProcessGroup {
  constructor(log = () => {}) { this.children = new Set(); this.log = log; this.stopping = false; }

  spawn(command, args, options = {}) {
    if (this.stopping) throw new Error('Startup was cancelled');
    // POSIX children lead their own process group; Windows children stay in this tree for taskkill /T.
    const child = spawn(command, args, { ...options, detached: !WINDOWS, windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe'] });
    this.children.add(child);
    child.on('error', error => { child.failure = error; });
    child.stdout.on('data', chunk => this.log(chunk));
    child.stderr.on('data', chunk => this.log(chunk));
    child.done = new Promise(resolve => {
      child.once('error', error => resolve({ error }));
      child.once('exit', (code, signal) => resolve({ code, signal }));
    });
    return child;
  }

  async run(command, args, options = {}, timeout = 60000) {
    const child = this.spawn(command, args, options);
    let timer;
    const result = await Promise.race([
      child.done,
      new Promise(resolve => { timer = setTimeout(() => resolve({ error: new Error('Command timed out') }), timeout); }),
    ]);
    clearTimeout(timer);
    if (result.error || result.code !== 0) {
      this.signal(child, 'SIGTERM');
      throw result.error ?? new Error(`${command} exited with ${result.code ?? result.signal}; see the runtime log`);
    }
    this.children.delete(child);
  }

  signal(child, signal) {
    if (!child.pid) return;
    if (WINDOWS) return void killTree(child.pid, this.log);
    try { process.kill(-child.pid, signal); }
    catch (error) { if (error.code !== 'ESRCH') this.log(`${error.message}\n`); }
  }

  running(child) {
    try { process.kill(WINDOWS ? child.pid : -child.pid, 0); return true; } catch { return false; }
  }

  alive(child) { return !child.failure && child.exitCode === null && child.signalCode === null; }

  async stop() {
    if (this.stopPromise) return this.stopPromise;
    this.stopping = true;
    this.stopPromise = (async () => {
      const children = [...this.children];
      for (const child of children) this.signal(child, 'SIGTERM');
      // A leader can exit before its children. Check process groups, not just PIDs.
      const deadline = Date.now() + 5000;
      while (Date.now() < deadline) {
        if (!children.some(child => child.pid && this.running(child))) break;
        await delay(100);
      }
      for (const child of children) this.signal(child, 'SIGKILL');
      await Promise.all(children.map(child => child.done));
      this.children.clear();
    })();
    return this.stopPromise;
  }
}

export function availablePort(preferred = 0) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', error => {
      if (preferred && error.code === 'EADDRINUSE') availablePort().then(resolve, reject);
      else reject(error);
    });
    server.listen(preferred, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

export function probe(url, { timeout = 2500 } = {}) {
  // Node HTTP deliberately bypasses shell/system proxy settings for loopback.
  return new Promise(resolve => {
    const request = http.get(url, { agent: false }, response => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 400);
    });
    const timer = setTimeout(() => request.destroy(), timeout);
    request.once('close', () => clearTimeout(timer));
    request.once('error', () => resolve(false));
  });
}

export async function waitReady(url, { signal, alive = () => true, timeout = 180000 } = {}) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    signal?.throwIfAborted();
    if (!alive()) throw new Error('A runtime process exited early; see the runtime log');
    if (await probe(url)) return;
    await delay(250, undefined, { signal });
  }
  throw new Error(`Timed out waiting for ${url}`);
}
