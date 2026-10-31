'use strict';

/**
 * DeepTutor desktop — main process entry point.
 *
 * Responsibilities, in order:
 *   1. build the privileged singletons (logger, config, path resolver);
 *   2. boot the local DeepTutor stack (backend + frontend) or attach to a
 *      running one;
 *   3. create a hardened window that renders the DeepTutor UI over loopback;
 *   4. wire menu, tray, IPC and lifecycle so the app behaves like a desktop
 *      citizen instead of a browser tab.
 *
 * The renderer never gets Node: it only sees `window.deeptutor`, exposed by the
 * sandboxed preload.
 */

const path = require('node:path');
const { app, dialog, nativeTheme } = require('electron');

const { Logger } = require('./logger');
const { ConfigStore } = require('./config-store');
const { RuntimePaths } = require('./runtime-paths');
const { ServiceManager } = require('./service-manager');
const { WindowManager } = require('./window-manager');
const { TrayController } = require('./tray');
const { installMenu } = require('./menu');
const { registerIpcHandlers } = require('./ipc');

const ROOT = path.resolve(__dirname, '..', '..');
const RENDERER_DIR = path.join(ROOT, 'src', 'renderer');
const PRELOAD_PATH = path.join(ROOT, 'src', 'preload', 'index.js');
const ASSETS_DIR = path.join(ROOT, 'build');

// --------------------------------------------------------------------------
// CLI arguments (also used by the smoke test harness)
// --------------------------------------------------------------------------

function parseArgs(argv) {
  const out = { _: [] };
  for (const raw of argv) {
    if (!raw.startsWith('--')) {
      out._.push(raw);
      continue;
    }
    const [key, ...rest] = raw.slice(2).split('=');
    const value = rest.length ? rest.join('=') : 'true';
    out[key] = value;
  }
  return out;
}

const ARGS = parseArgs(process.argv.slice(1));
const IS_DEV = ARGS.dev === 'true' || !app.isPackaged;
const IS_SMOKE = ARGS.smoke === 'true';

if (ARGS['user-data']) {
  app.setPath('userData', path.resolve(ARGS['user-data']));
}

// --------------------------------------------------------------------------
// Early singletons — config must be readable before `ready` so a user can turn
// hardware acceleration off and still get a usable window.
// --------------------------------------------------------------------------

const userDataDir = app.getPath('userData');
const logger = new Logger({ dir: path.join(userDataDir, 'logs'), level: IS_DEV ? 'debug' : 'info' });
const config = new ConfigStore({ filePath: path.join(userDataDir, 'config.json'), logger });
config.load();

function applyCliOverrides() {
  const patch = {};
  if (ARGS['backend-port']) patch.backendPort = Number(ARGS['backend-port']);
  if (ARGS['frontend-port']) patch.frontendPort = Number(ARGS['frontend-port']);
  if (ARGS.home) patch.home = path.resolve(ARGS.home);
  if (ARGS['python-path']) patch.pythonPath = path.resolve(ARGS['python-path']);
  if (ARGS['reuse-running']) patch.reuseRunning = ARGS['reuse-running'] !== 'false';
  if (ARGS['no-reuse']) patch.reuseRunning = false;
  if (Object.keys(patch).length) {
    config.set({ service: { ...config.get('service'), ...patch } });
    logger.info(`cli overrides: ${JSON.stringify(patch)}`);
  }
}
applyCliOverrides();

if (!config.get('behavior.hardwareAcceleration') || ARGS['disable-gpu'] === 'true') {
  app.disableHardwareAcceleration();
  logger.info('hardware acceleration disabled');
}

if (process.platform === 'win32') {
  app.setAppUserModelId('info.deeptutor.desktop');
}

nativeTheme.themeSource = config.get('ui.theme') || 'system';

// --------------------------------------------------------------------------
// Single instance: a second launch focuses the existing window instead of
// starting a second stack on the same ports.
// --------------------------------------------------------------------------

if (!IS_SMOKE) {
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) {
    app.quit();
  }
}

// --------------------------------------------------------------------------
// Boot
// --------------------------------------------------------------------------

let service = null;
let windows = null;
let tray = null;
let disposeIpc = null;
let shuttingDown = false;

function bootstrap() {
  logger.info(`booting DeepTutor desktop ${app.getVersion()} (packaged=${app.isPackaged}, dev=${IS_DEV})`);

  const paths = new RuntimePaths({ app, config, logger });
  const iconPath = path.join(ASSETS_DIR, 'icon.png');
  const trayIconPath = path.join(ASSETS_DIR, 'tray.png');

  service = new ServiceManager({ config, paths, logger });
  windows = new WindowManager({
    app,
    config,
    logger,
    service,
    rendererDir: RENDERER_DIR,
    preloadPath: PRELOAD_PATH,
    iconPath,
    isDev: IS_DEV,
  });

  disposeIpc = registerIpcHandlers({ config, service, windows, paths, logger });

  windows.createMainWindow();

  installMenu({ windows, service, config, logger, paths, isDev: IS_DEV });

  if (ARGS['no-tray'] !== 'true') {
    tray = new TrayController({ windows, service, config, logger, iconPath: trayIconPath });
    try {
      tray.create();
    } catch (error) {
      logger.warn(`tray unavailable: ${error.message}`);
      tray = null;
    }
  } else {
    logger.info('tray disabled by flag');
  }

  service.on('status', (status) => {
    tray?.update(status);
    windows.onServiceStatus(status);
    if (status.state === 'ready') {
      windows.onServiceReady();
      if (tray) tray.update(status);
    }
    if (status.state === 'error' && !IS_SMOKE) {
      logger.error(`service error: ${status.message}`);
    }
  });

  config.on('changed', (next) => windows.broadcast('config:changed', next));

  if (IS_DEV) {
    process.on('unhandledRejection', (reason) => logger.error(`unhandled rejection: ${reason}`));
  }

  if (config.get('service.autoStart')) {
    service.start().catch((error) => {
      logger.error(`startup failed: ${error.message}`);
      windows.onServiceStatus(service.getStatus());
    });
  } else {
    logger.info('autoStart disabled — waiting for a manual restart');
  }

  if (ARGS['launch-hidden'] === 'true') {
    windows.mainWindow?.hide();
  }

  if (IS_SMOKE) {
    // Loaded lazily: the harness must not exist in a production bundle path.
    require('./smoke').runSmoke({
      app,
      config,
      service,
      windows,
      paths,
      logger,
      outPath: ARGS['smoke-out'] ? path.resolve(ARGS['smoke-out']) : path.join(userDataDir, 'smoke-report.json'),
      timeoutMs: Number(ARGS['smoke-timeout'] || 240000),
    });
  }
}

app.whenReady().then(bootstrap).catch((error) => {
  logger.error(`bootstrap failed: ${error.stack || error.message}`);
  dialog.showErrorBox('DeepTutor 启动失败', error.message);
  app.exit(1);
});

app.on('second-instance', () => {
  logger.info('second instance detected — focusing existing window');
  windows?.show();
});

app.on('activate', () => {
  if (!windows) return;
  if (windows.windows.size === 0) windows.createMainWindow();
  else windows.show();
});

app.on('window-all-closed', () => {
  // With close-to-tray the window is hidden, not closed, so this only fires
  // when the user really means to leave.
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', async (event) => {
  if (shuttingDown) return;
  shuttingDown = true;
  event.preventDefault();

  try {
    if (windows && !windows.confirmQuit()) {
      shuttingDown = false;
      return;
    }
    logger.info('shutting down');
    windows?.prepareQuit();
    tray?.destroy();
    disposeIpc?.();
    await service?.stop({ silent: true });
  } catch (error) {
    logger.error(`shutdown error: ${error.message}`);
  } finally {
    config.flush();
    logger.info('bye');
    logger.flush();
    app.exit(0);
  }
});

process.on('uncaughtException', (error) => {
  logger.error(`uncaught exception: ${error.stack || error.message}`);
});
