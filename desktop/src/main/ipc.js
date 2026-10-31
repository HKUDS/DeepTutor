'use strict';

/**
 * The only bridge between the sandboxed renderer and the privileged main
 * process.
 *
 * Rules enforced here:
 *   - every channel is explicitly listed; nothing is proxied generically;
 *   - every payload is shape-checked before it reaches a module;
 *   - errors are returned as data (`{ ok: false }`) instead of raw stack traces,
 *     so a failure in main can never leak internals into the page.
 */

const { app, BrowserWindow, ipcMain, shell } = require('electron');

const SAFE_PROTOCOLS = new Set(['http:', 'https:', 'mailto:']);

function asObject(payload) {
  return payload && typeof payload === 'object' ? payload : {};
}

function safeExternalUrl(raw) {
  if (typeof raw !== 'string') return null;
  try {
    const url = new URL(raw);
    if (!SAFE_PROTOCOLS.has(url.protocol)) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function windowFromSender(event) {
  return BrowserWindow.fromWebContents(event.sender);
}

function ok(data) {
  return { ok: true, data };
}

function fail(error) {
  return { ok: false, error: error?.message || String(error) };
}

function registerIpcHandlers({ config, service, windows, paths, logger }) {
  const log = logger.scope('ipc');

  const handle = (channel, handler) => {
    ipcMain.handle(channel, async (event, payload) => {
      try {
        return await handler(asObject(payload), event);
      } catch (error) {
        log.error(`${channel} failed: ${error.message}`);
        return fail(error);
      }
    });
  };

  handle('app:info', () => ok({
    name: app.getName(),
    version: app.getVersion(),
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
    platform: process.platform,
    arch: process.arch,
    packaged: app.isPackaged,
    userData: app.getPath('userData'),
    logFile: logger.filePath,
    runtime: paths.describe(),
  }));

  handle('app:quit', () => {
    app.quit();
    return ok(true);
  });

  handle('config:get', ({ key }) => {
    if (typeof key === 'string' && key) return ok(config.get(key));
    return ok(config.all());
  });

  handle('config:set', ({ patch }) => {
    if (!patch || typeof patch !== 'object') throw new Error('patch 必须是对象');
    return ok(config.set(patch));
  });

  handle('config:reset', () => ok(config.reset()));

  handle('service:status', () => ok(service.getStatus()));

  handle('service:restart', async () => {
    log.info('restart requested from renderer');
    const status = await service.restart();
    return ok(status);
  });

  handle('service:openLogs', () => {
    shell.openPath(app.getPath('userData'));
    return ok(true);
  });

  handle('service:openWorkspace', () => {
    shell.openPath(paths.home());
    return ok(true);
  });

  handle('shell:openExternal', ({ url }) => {
    const safe = safeExternalUrl(url);
    if (!safe) throw new Error('仅允许打开 http/https/mailto 链接');
    if (!windows.openExternal(safe)) throw new Error('外部链接打开被禁用');
    return ok(safe);
  });

  handle('window:action', ({ action }, event) => {
    const win = windowFromSender(event) || windows.mainWindow;
    if (!win || win.isDestroyed()) throw new Error('窗口不可用');
    switch (action) {
      case 'minimize':
        win.minimize();
        break;
      case 'maximize':
        if (win.isMaximized()) win.unmaximize();
        else win.maximize();
        break;
      case 'fullscreen':
        win.setFullScreen(!win.isFullScreen());
        break;
      case 'close':
        win.close();
        break;
      case 'reload':
        windows.loadApp(win);
        break;
      case 'devtools':
        windows.toggleDevTools();
        break;
      default:
        throw new Error(`未知的窗口操作: ${String(action)}`);
    }
    return ok({
      maximized: win.isMaximized(),
      fullscreen: win.isFullScreen(),
    });
  });

  handle('window:state', (_payload, event) => {
    const win = windowFromSender(event) || windows.mainWindow;
    if (!win || win.isDestroyed()) return ok(null);
    return ok({
      maximized: win.isMaximized(),
      fullscreen: win.isFullScreen(),
      focused: win.isFocused(),
      visible: win.isVisible(),
    });
  });

  // Renderer -> main fire-and-forget events that don't need a response.
  ipcMain.on('window:action:sync', (event, payload) => {
    const action = asObject(payload).action;
    try {
      const win = windowFromSender(event) || windows.mainWindow;
      if (!win || win.isDestroyed()) return;
      if (action === 'minimize') win.minimize();
      else if (action === 'close') win.close();
      else if (action === 'maximize') {
        if (win.isMaximized()) win.unmaximize();
        else win.maximize();
      }
    } catch (error) {
      log.warn(`sync window action failed: ${error.message}`);
    }
  });

  return () => {
    for (const channel of [
      'app:info', 'app:quit', 'config:get', 'config:set', 'config:reset',
      'service:status', 'service:restart', 'service:openLogs', 'service:openWorkspace',
      'shell:openExternal', 'window:action', 'window:state',
    ]) {
      ipcMain.removeHandler(channel);
    }
  };
}

module.exports = { registerIpcHandlers };
