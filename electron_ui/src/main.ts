import { app, BrowserWindow, dialog, ipcMain, Menu, MenuItemConstructorOptions, shell, Tray } from 'electron';
import * as childProcess from 'node:child_process';
import * as os from 'node:os';
import * as fs from 'node:fs';
import * as net from 'node:net';
import * as path from 'node:path';

const APP_NAME = 'DeepTutor';
const DEFAULT_BACKEND_PORT = 8001;
const DEFAULT_FRONTEND_PORT = 3782;
const SETTINGS_DIR = path.join('data', 'user', 'settings');
const SETTINGS_FILE = 'system.json';
const FRONTEND_WAIT_MS = 180_000;

// Development runs from the source tree; packaged builds place the app sources
// inside app.asar while Python/Web assets are unpacked under resources/app.
const isDev = !app.isPackaged;
const APP_ROOT = isDev
  ? path.resolve(__dirname, '..', '..')
  : path.join(process.resourcesPath, 'app');
const INDEX_HTML = path.join(__dirname, '..', 'index.html');

function getRuntimeHome(): string {
  const env = process.env.DEEPTUTOR_HOME;
  if (env && fs.existsSync(env)) return env;
  return path.join(app.getPath('appData'), APP_NAME);
}

function resolveIconPath(name: string): string {
  // In dev mode, __dirname is electron_ui/dist/ so '..' goes to electron_ui/,
  // and '../assets/figs/logo/name' resolves correctly.
  // In packaged mode, __dirname is inside app.asar (asar:///.../dist/).
  // fs.existsSync on asar paths returns false, so we fall through to the
  // filesystem search starting from process.resourcesPath (the resources/ dir).
  const asarPath = path.join(__dirname, 'assets', 'figs', 'logo', name);
  if (fs.existsSync(asarPath)) return asarPath;
  const candidates = isDev
    ? [path.join(APP_ROOT, 'assets', 'figs', 'logo', name)]
    : [
        // extraFiles places assets at the unpacked root (same level as exe)
        path.join(process.resourcesPath, '..', 'assets', 'figs', 'logo', name),
        // fallback: inside the asar if bundled there
        path.join(process.resourcesPath, 'app.asar', 'assets', 'figs', 'logo', name),
      ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  // Last resort: use the asar path (may fail, but gives a clear error)
  return asarPath;
}

interface BackendLaunch {
  command: string;
  args: string[];
  /** True when command is a frozen deeptutor.exe (not a Python interpreter). */
  frozen: boolean;
}

function resolvePackagedBackendExe(): string | null {
  const candidates = [
    // extraFiles `to: python-backend` → next to resources/ (same level as exe)
    path.join(process.resourcesPath, '..', 'python-backend', 'deeptutor.exe'),
    path.join(process.resourcesPath, 'python-backend', 'deeptutor.exe'),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

function resolveWebDir(): string | null {
  const candidates = isDev
    ? [path.join(APP_ROOT, 'deeptutor_web')]
    : [
        path.join(process.resourcesPath, '..', 'deeptutor_web'),
        path.join(process.resourcesPath, 'app', 'deeptutor_web'),
        path.join(process.resourcesPath, 'deeptutor_web'),
      ];
  for (const candidate of candidates) {
    if (fs.existsSync(path.join(candidate, 'server.js'))) return candidate;
  }
  return null;
}

function resolveNodeBinDir(): string | null {
  const candidates = isDev
    ? [
        path.join(APP_ROOT, 'packaging', 'node-runtime', 'win-x64'),
        path.join(APP_ROOT, 'packaging', 'node-runtime', 'node-runtime-bundle', 'bin'),
        path.join(APP_ROOT, 'packaging', 'node-runtime', 'bin'),
      ]
    : [
        path.join(process.resourcesPath, '..', 'node-runtime'),
        path.join(process.resourcesPath, 'node-runtime'),
        path.join(process.resourcesPath, '..', 'node-runtime', 'bin'),
        path.join(process.resourcesPath, 'node-runtime', 'bin'),
      ];
  for (const candidate of candidates) {
    const exe = path.join(candidate, process.platform === 'win32' ? 'node.exe' : 'node');
    if (fs.existsSync(exe)) return candidate;
  }
  return null;
}

function resolveBackend(runtimeHome: string): BackendLaunch {
  const custom = process.env.DEEPTUTOR_PYTHON;
  if (custom) {
    const base = path.basename(custom).toLowerCase();
    const frozen = base === 'deeptutor.exe' || base === 'deeptutor';
    if (frozen) {
      return {
        command: custom,
        args: ['start', '--home', runtimeHome, '--no-browser'],
        frozen: true,
      };
    }
    return {
      command: custom,
      args: ['-m', 'deeptutor_cli.main', 'start', '--home', runtimeHome, '--no-browser'],
      frozen: false,
    };
  }
  if (!isDev) {
    const bundled = resolvePackagedBackendExe();
    if (bundled) {
      return {
        command: bundled,
        args: ['start', '--home', runtimeHome, '--no-browser'],
        frozen: true,
      };
    }
  }
  return {
    command: 'python',
    args: ['-m', 'deeptutor_cli.main', 'start', '--home', runtimeHome, '--no-browser'],
    frozen: false,
  };
}

function prepareSettings(runtimeHome: string, backendPort: number, frontendPort: number): void {
  const settingsDir = path.join(runtimeHome, SETTINGS_DIR);
  fs.mkdirSync(settingsDir, { recursive: true });
  const sysPath = path.join(settingsDir, SETTINGS_FILE);
  let existing: Record<string, unknown> = {};
  if (fs.existsSync(sysPath)) {
    try { existing = JSON.parse(fs.readFileSync(sysPath, 'utf8')); } catch { /* ignore */ }
  }
  const updated = { ...existing, backend_port: backendPort, frontend_port: frontendPort };
  fs.writeFileSync(sysPath, JSON.stringify(updated, null, 2), 'utf8');
}

function readPorts(runtimeHome: string): { backendPort: number; frontendPort: number } {
  try {
    const sysPath = path.join(runtimeHome, SETTINGS_DIR, SETTINGS_FILE);
    if (fs.existsSync(sysPath)) {
      const sys = JSON.parse(fs.readFileSync(sysPath, 'utf8')) as Record<string, unknown>;
      return {
        backendPort: Number(sys['backend_port']) || DEFAULT_BACKEND_PORT,
        frontendPort: Number(sys['frontend_port']) || DEFAULT_FRONTEND_PORT,
      };
    }
  } catch { /* ignore */ }
  return { backendPort: DEFAULT_BACKEND_PORT, frontendPort: DEFAULT_FRONTEND_PORT };
}

function isPortInUse(port: number): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    const s = net.createConnection({ port, host: '127.0.0.1' }, () => { s.destroy(); resolve(true); });
    s.once('error', () => resolve(false));
  }).catch(() => false);
}

async function findFreePort(preferred: number, taken: Set<number> = new Set()): Promise<number> {
  for (let p = preferred; p < preferred + 200; p++) {
    if (taken.has(p)) continue;
    if (!(await isPortInUse(p))) return p;
  }
  return preferred;
}

// ---------------------------------------------------------------------------
// Process-tree cleanup. On Windows, taskkill /T tears down the whole tree,
// which prevents orphaned uvicorn/node children from holding file locks.
// ---------------------------------------------------------------------------
function killProcessTree(pid: number): void {
  if (os.platform() !== 'win32') {
    try { process.kill(pid, 'SIGTERM'); } catch { /* ignore */ }
    return;
  }
  try {
    childProcess.execSync('taskkill /PID ' + pid + ' /F /T', {
      encoding: 'utf8', windowsHide: true, timeout: 10_000,
    });
    console.log('[Electron] Killed process tree PID=' + pid);
  } catch { /* already gone */ }
}

// Kill any stale deeptutor launcher processes from previous runs. These can be
// orphaned if a prior session crashed, leaving uvicorn/node holding locks on
// the runtime web directory.
// Clean up stale runtime web directory left by crashed prior sessions.
// The launcher copies deeptutor_web assets here; leftover locked files cause
// PermissionError on the next start. We remove the whole directory tree before
// spawning the launcher so _copy_packaged_web_if_needed can recreate it fresh.
function cleanupRuntimeWeb(runtimeHome: string): void {
  const webDir = path.join(runtimeHome, 'data', 'user', 'runtime', 'web');
  if (!fs.existsSync(webDir)) return;
  try {
    fs.rmSync(webDir, { recursive: true, force: true });
    console.log('[Electron] Cleaned up stale runtime web dir: ' + webDir);
  } catch (err) {
    // Files may be locked by a previous crashed session. The launcher will
    // attempt its own copy and may succeed if locks are released.
    console.warn('[Electron] Could not clean runtime web dir (files may be locked): ' + (err instanceof Error ? err.message : String(err)));
  }
}

function killStaleProcesses(): void {
  if (os.platform() !== 'win32') return;
  // Fast path: kill any python/node processes on our known ports.
  // Avoid per-PID PowerShell queries which are too slow.
  try {
    const result = childProcess.execSync('netstat -ano', { encoding: 'utf8', windowsHide: true, timeout: 5000 });
    for (const line of result.split(/\r?\n/)) {
      if (!line.includes('LISTENING')) continue;
      const parts = line.trim().split(/\s+/);
      const pid = parseInt(parts[parts.length - 1], 10);
      if (Number.isNaN(pid)) continue;
      const addr = parts[1] || '';
      if (addr.includes(':8001') || addr.includes(':8002') || addr.includes(':3782') || addr.includes(':3783')) {
        killProcessTree(pid);
      }
    }
  } catch { /* proceed anyway */ }
}

interface LauncherState {
  process: childProcess.ChildProcess | null;
  frontendUrl: string | null;
  error: string | null;
  backendPort: number;
  frontendPort: number;
  runtimeHome: string;
}

let launcher: LauncherState | null = null;
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;

// Poll a URL until it responds, so we can wait for the backend/frontend to be
// ready instead of relying only on stdout parsing (mirrors a retry + health
// check).
function waitForHttp(url: string, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  return new Promise<boolean>((resolve) => {
    const tick = () => {
      if (Date.now() > deadline) { resolve(false); return; }
      try {
        const req = net.createConnection({ port: Number(new URL(url).port) || 80, host: '127.0.0.1' });
        req.setTimeout(1500);
        req.once('connect', () => { req.destroy(); resolve(true); });
        req.once('error', () => req.destroy());
        req.once('timeout', () => req.destroy());
      } catch { /* fallthrough */ }
      setTimeout(tick, 1000);
    };
    tick();
  });
}

async function startLauncher(): Promise<LauncherState> {
  const runtimeHome = getRuntimeHome();
  let { backendPort, frontendPort } = readPorts(runtimeHome);
  const portChecks = await Promise.all([isPortInUse(backendPort), isPortInUse(frontendPort)]);
  if (portChecks[0] || portChecks[1]) {
    const taken = new Set<number>();
    if (portChecks[0]) taken.add(backendPort);
    if (portChecks[1]) taken.add(frontendPort);
    backendPort = await findFreePort(backendPort, taken);
    frontendPort = await findFreePort(frontendPort, taken);
    console.log('[Electron] Port conflict resolved: backend=' + backendPort + ', frontend=' + frontendPort);
  }
  prepareSettings(runtimeHome, backendPort, frontendPort);
  const backend = resolveBackend(runtimeHome);
  const webDir = resolveWebDir();
  const nodeBin = resolveNodeBinDir();
  const pathParts = [nodeBin, process.env.PATH].filter(Boolean) as string[];
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    DEEPTUTOR_HOME: runtimeHome,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    PYTHONUNBUFFERED: '1',
    PATH: pathParts.join(path.delimiter),
  };
  if (webDir) {
    env.DEEPTUTOR_WEB_DIR = webDir;
  }
  // Source / interpreter mode still needs the checkout on PYTHONPATH.
  if (!backend.frozen) {
    env.PYTHONPATH = APP_ROOT;
    env.PROJECT_ROOT = APP_ROOT;
  }
  console.log('[Electron] Spawning launcher: ' + backend.command + ' ' + backend.args.join(' '));
  const proc = childProcess.spawn(backend.command, backend.args, {
    env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true, cwd: APP_ROOT,
  });
  const state: LauncherState = {
    process: proc as unknown as childProcess.ChildProcess,
    frontendUrl: null, error: null, backendPort, frontendPort, runtimeHome,
  };
  launcher = state;

  let buffer = '';
  proc.stdout.on('data', (chunk: Buffer) => {
    buffer += chunk.toString('utf8');
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      const m = line.match(/https?:\/\/[^\s:]+:\d+(?:\/\S*)?/i);
      if (m && !state.frontendUrl) {
        const rawUrl = m[0];
        if (!rawUrl || rawUrl.length < 4) continue;
        let port = 0;
        try {
          port = new URL(rawUrl).port ? Number(new URL(rawUrl).port) : state.frontendPort;
        } catch {
          continue;
        }
        // Only accept front-end URLs for the configured launcher port; ignore unrelated URLs from logs.
        if (port !== state.frontendPort) continue;
        let url = rawUrl.replace('localhost', '127.0.0.1');
        // Keep whatever port the launcher actually bound.
        if (state.frontendPort) url = url.replace(/:\d+/, ':' + state.frontendPort);
        state.frontendUrl = url;
        console.log('[Electron] Frontend URL detected: ' + url);
      }
    }
  });
  proc.stderr.on('data', (chunk: Buffer) => {
    const msg = chunk.toString('utf8').trim();
    if (msg) console.error('[Electron][stderr] ' + msg);
    if (!state.error) state.error = msg;
  });
  proc.on('error', (err: Error) => {
    state.error = err.message;
    console.error('[Electron] Launcher spawn error:', err.message);
  });
  proc.on('close', (code) => {
    console.log('[Electron] Launcher exited code=' + code);
    if (launcher === state) launcher = null;
    if (code !== 0 && code !== null && mainWindow) {
      const msg = 'Launcher exited with code ' + code;
      notifyError(msg);
      console.error('[Electron]', msg);
    }
  });

  // Wait for a frontend URL via health check, with a bounded timeout.
  // Use interval-based polling (not a blocking while-loop) so the event loop
  // stays responsive and the stdout handler can update state.frontendUrl.
  const fallbackUrl = 'http://127.0.0.1:' + frontendPort + '/';
  const deadline = Date.now() + FRONTEND_WAIT_MS;
  // Only consider the frontend ready when we can actually HTTP-connect to it.
  // The stdout URL detection is just a hint — the real signal is the health check.
  while (launcher === state && Date.now() < deadline) {
    if (await waitForHttp(fallbackUrl, 3000)) {
      state.frontendUrl = fallbackUrl;
      console.log('[Electron] Frontend reachable at ' + fallbackUrl);
      break;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  if (launcher === state && !state.frontendUrl) {
    state.error = state.error || 'Backend/frontend did not become ready within ' + (FRONTEND_WAIT_MS / 1000) + 's';
    console.error('[Electron]', state.error);
  }
  return state;
}

function stopLauncher(): void {
  if (!launcher?.process) return;
  const proc = launcher.process;
  const pid = proc.pid;
  launcher = null;
  if (pid) killProcessTree(pid);
}

function notifyError(msg: string): void {
  if (mainWindow?.webContents) {
    mainWindow.webContents.send('app:error', msg);
  }
  dialog.showErrorBox(APP_NAME, msg);
}

function createWindow(frontendUrl: string, iconPath?: string): BrowserWindow {
  const win = new BrowserWindow({
    width: 1400, height: 900, minWidth: 800, minHeight: 600, frame: true, title: APP_NAME,
    autoHideMenuBar: false,
    icon: iconPath || resolveIconPath('logo.png'),
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false },
  });
  win.loadFile(INDEX_HTML, { query: { url: frontendUrl } });
  // Explicitly show window -- BrowserWindow may be created hidden depending on prefs
  win.show();
  win.on('closed', () => {
    mainWindow = null;
    // Keep tray alive — single icon regardless of window count
  });
  return win;
}

// ---------------------------------------------------------------------------
// Application menu bar (visible when frame: false)
// ---------------------------------------------------------------------------
function buildApplicationMenu(): Menu {
  const isRunning = launcher !== null && launcher.process?.exitCode === null;
  const hasFrontend = !!launcher?.frontendUrl;
  const template: MenuItemConstructorOptions[] = [
    {
      label: 'File',
      submenu: [
        {
          label: mainWindow?.isVisible() ? 'Hide' : 'Show',
          accelerator: 'CmdOrCtrl+H',
          click: () => { if (mainWindow) { mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show(); } },
        },
        { type: 'separator' },
        {
          label: isRunning ? 'Stop DeepTutor' : 'Start DeepTutor',
          accelerator: 'CmdOrCtrl+Shift+S',
          click: () => {
            if (isRunning) { stopLauncher(); mainWindow?.close(); }
            else { void startAndShow(); }
          },
        },
        {
          label: 'Restart',
          accelerator: 'CmdOrCtrl+Shift+R',
          click: () => { void restartApp(); },
        },
        { type: 'separator' },
        { label: 'Quit', accelerator: 'CmdOrCtrl+Q', click: () => { app.quit(); } },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload', accelerator: 'CmdOrCtrl+R' },
        { role: 'forceReload' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
        { type: 'separator' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { role: 'resetZoom' },
        { type: 'separator' },
        { role: 'toggleDevTools' },
      ],
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Open in Browser',
          enabled: hasFrontend,
          click: () => { if (hasFrontend) shell.openExternal(launcher!.frontendUrl!); },
        },
        { type: 'separator' },
        {
          label: 'About DeepTutor',
          click: () => {
            dialog.showMessageBox({
              type: 'info',
              title: 'About DeepTutor',
              message: APP_NAME,
              detail: 'Agent-native intelligent learning companion.\n' +
                      'Backend: http://127.0.0.1:' + (launcher?.backendPort || DEFAULT_BACKEND_PORT) + '\n' +
                      'Frontend: ' + (launcher?.frontendUrl || 'not started'),
              buttons: ['OK'],
            });
          },
        },
      ],
    },
  ];
  return Menu.buildFromTemplate(template);
}

function buildContextMenu(): Menu {
  const isRunning = launcher !== null && launcher.process?.exitCode === null;
  const items: MenuItemConstructorOptions[] = [
    {
      label: mainWindow?.isVisible() ? 'Hide' : 'Show',
      click: () => { if (mainWindow) { mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show(); } },
    },
    { type: 'separator' },
    { label: 'Restart', click: () => { void restartApp(); } },
    {
      label: isRunning ? 'Stop' : 'Start',
      click: () => {
        if (isRunning) { stopLauncher(); mainWindow?.close(); }
        else { void startAndShow(); }
      },
    },
    { type: 'separator' },
    {
      label: 'Open in Browser',
      enabled: !!launcher?.frontendUrl,
      click: () => { if (launcher?.frontendUrl) shell.openExternal(launcher.frontendUrl); },
    },
    { type: 'separator' },
    { label: 'Quit', click: () => { app.quit(); } },
  ];
  return Menu.buildFromTemplate(items);
}

function createTray(): void {
  if (tray) { tray.destroy(); tray = null; }
  console.log('[Electron] createTray called');
  const iconPath = resolveIconPath('logo.png');
  console.log('[Electron] iconPath=' + iconPath + ' exists=' + fs.existsSync(iconPath));
  const t = new Tray(iconPath);
  tray = t;
  t.setToolTip(APP_NAME);
  t.setContextMenu(buildContextMenu());
  t.on('double-click', () => { if (mainWindow) { mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show(); } });
  t.on('right-click', () => t.setContextMenu(buildContextMenu()));
}

async function startAndShow(): Promise<void> {
  console.log('[Electron] startAndShow called, launcher=' + (launcher ? 'exists' : 'null'));
  if (launcher?.process?.exitCode === null) {
    console.log('[Electron] launcher already running, skipping');
    return;
  }
  stopLauncher();
  const homeForCleanup = getRuntimeHome();
  cleanupRuntimeWeb(homeForCleanup);
  console.log('[Electron] About to killStaleProcesses...');
  killStaleProcesses();
  console.log('[Electron] Stale processes cleared.');
  try {
    const state = await startLauncher();
    if (!state.frontendUrl) {
      notifyError(state.error || 'Frontend did not start');
      return;
    }
    // Close existing window gracefully before creating a new one.
    if (mainWindow) {
      mainWindow.close();
      await new Promise<void>((resolve) => {
        if (!mainWindow || mainWindow.isDestroyed()) { resolve(); return; }
        mainWindow.once('closed', () => resolve());
        setTimeout(resolve, 1000);
      });
    }
    console.log('[Electron] About to createWindow...');
    const iconPath = resolveIconPath('logo.png');
    mainWindow = createWindow(state.frontendUrl, iconPath);
    createTray();
    console.log('[Electron] Window created, frontendUrl=' + state.frontendUrl);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    notifyError(msg);
    console.error('[Electron] Start failed:', msg);
  }
}

async function restartApp(): Promise<void> {
  stopLauncher();
  await new Promise((r) => setTimeout(r, 1500));
  await startAndShow();
}

function setupIpc(): void {
  ipcMain.handle('app:start', async () => { await startAndShow(); return { ok: true }; });
  ipcMain.handle('app:stop', () => { stopLauncher(); mainWindow?.close(); return { ok: true }; });
  ipcMain.handle('app:restart', async () => { await restartApp(); return { ok: true }; });
  ipcMain.handle('app:get-status', () => {
    if (!launcher) return { running: false, frontendUrl: null as string | null, error: null as string | null };
    return { running: launcher.process?.exitCode === null, frontendUrl: launcher.frontendUrl, error: launcher.error };
  });
  ipcMain.handle('app:get-config', () => {
    const home = getRuntimeHome();
    const { backendPort, frontendPort } = readPorts(home);
    return { backendPort, frontendPort, home };
  });
}

// Single-instance lock: second launch brings the existing window to front
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.exit();
} else {
  app.on('second-instance', (_event, _argv) => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    } else { void startAndShow(); }
  });
}

app.whenReady().then(async () => {
  const home = getRuntimeHome();
  fs.mkdirSync(home, { recursive: true });
  console.log('[Electron] App ready, home=' + home);
  console.log('[Electron] isPackaged=' + app.isPackaged + ', resourcesPath=' + process.resourcesPath);
  console.log('[Electron] INDEX_HTML=' + INDEX_HTML + ' exists=' + fs.existsSync(INDEX_HTML));
  setupIpc();
  createTray();
  await startAndShow();
});

// Terminate the launcher process tree before quitting so no orphaned
// uvicorn/node children remain.
app.on('before-quit', () => {
  stopLauncher();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    if (launcher?.frontendUrl) {
      mainWindow = createWindow(launcher.frontendUrl);
      createTray();
    }
    else { void startAndShow(); }
  }
});
