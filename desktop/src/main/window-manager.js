'use strict';

/**
 * Window lifecycle: one main window plus optional secondary windows, a splash
 * page while the backend boots, and a recoverable error page when it does not.
 *
 * All windows are created with the same hardened webPreferences — context
 * isolation on, Node off, sandbox on, single preload bridge — so it does not
 * matter whether the content is the splash page or the DeepTutor UI.
 */

const path = require('node:path');
const { BrowserWindow, dialog, shell } = require('electron');
const { attachExternalLinkPolicy, sameOrigin } = require('./external-links');

const SPLASH_FILE = 'splash.html';
const ERROR_FILE = 'error.html';

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, wait);
    if (typeof timer.unref === 'function') timer.unref();
  };
}

class WindowManager {
  constructor({ app, config, logger, service, rendererDir, preloadPath, iconPath, isDev }) {
    this.app = app;
    this.config = config;
    this.logger = logger.scope('windows');
    this.service = service;
    this.rendererDir = rendererDir;
    this.preloadPath = preloadPath;
    this.iconPath = iconPath;
    this.isDev = isDev;
    this.windows = new Set();
    this.mainWindow = null;
    this.quitting = false;
    this.persistBounds = debounce(() => this.#saveWindowState(), 400);
    this.persistUrl = debounce((url) => this.#saveLastUrl(url), 800);
  }

  #webPreferences() {
    return {
      preload: this.preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      sandbox: true,
      webviewTag: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
      spellcheck: true,
      devTools: true,
      backgroundThrottling: false,
      zoomFactor: this.config.get('window.zoomFactor') || 1,
    };
  }

  createMainWindow() {
    if (this.mainWindow && !this.mainWindow.isDestroyed()) {
      this.mainWindow.show();
      this.mainWindow.focus();
      return this.mainWindow;
    }
    const win = this.#createWindow({ restoreBounds: true });
    this.mainWindow = win;
    return win;
  }

  createSecondaryWindow() {
    const win = this.#createWindow({ restoreBounds: false });
    this.#loadSplashOrApp(win);
    return win;
  }

  #createWindow({ restoreBounds }) {
    const state = this.config.get('window');
    const options = {
      width: state.width,
      height: state.height,
      minWidth: 900,
      minHeight: 600,
      show: false,
      title: 'DeepTutor',
      backgroundColor: '#f6f7f9',
      autoHideMenuBar: false,
      webPreferences: this.#webPreferences(),
    };

    if (this.iconPath) options.icon = this.iconPath;
    if (restoreBounds && Number.isInteger(state.x) && Number.isInteger(state.y)) {
      options.x = state.x;
      options.y = state.y;
    }

    const win = new BrowserWindow(options);
    this.windows.add(win);

    if (state.alwaysOnTop) win.setAlwaysOnTop(true);
    if (restoreBounds && state.maximized) win.maximize();

    this.#wire(win, { restoreBounds });
    this.#loadSplashOrApp(win);
    return win;
  }

  #wire(win, { restoreBounds }) {
    const contents = win.webContents;

    attachExternalLinkPolicy(contents, {
      appOrigin: () => this.service.url,
      openExternal: (url) => this.openExternal(url),
      logger: this.logger,
      onNewWindow: (child) => {
        if (child && !child.isDestroyed()) child.setMenu(null);
      },
    });

    win.once('ready-to-show', () => {
      win.show();
      if (this.config.get('behavior.openDevTools') && this.isDev) {
        contents.openDevTools({ mode: 'detach' });
      }
    });

    win.on('resize', () => restoreBounds && this.persistBounds());
    win.on('move', () => restoreBounds && this.persistBounds());
    win.on('maximize', () => {
      this.#broadcastWindowState(win);
      if (restoreBounds) this.persistBounds();
    });
    win.on('unmaximize', () => {
      this.#broadcastWindowState(win);
      if (restoreBounds) this.persistBounds();
    });
    win.on('enter-full-screen', () => {
      this.#broadcastWindowState(win);
      if (restoreBounds) this.persistBounds();
    });
    win.on('leave-full-screen', () => {
      this.#broadcastWindowState(win);
      if (restoreBounds) this.persistBounds();
    });

    win.on('minimize', (event) => {
      if (this.config.get('behavior.minimizeToTray')) {
        event.preventDefault();
        win.hide();
      }
    });

    win.on('close', (event) => {
      if (this.quitting) return;
      if (this.config.get('behavior.closeToTray') && this.service.isReady()) {
        event.preventDefault();
        win.hide();
        this.logger.info('close intercepted: hiding to tray');
      }
    });

    win.on('closed', () => {
      this.windows.delete(win);
      if (win === this.mainWindow) this.mainWindow = null;
    });

    contents.on('did-fail-load', (_event, errorCode, errorDescription, validatedUrl, isMainFrame) => {
      if (!isMainFrame || errorCode === -3 /* aborted, e.g. superseded navigation */) return;
      this.logger.warn(`did-fail-load ${errorCode} ${errorDescription} (${validatedUrl})`);
      if (this.service.isReady() && sameOrigin(validatedUrl, this.service.url)) {
        this.showError(win, {
          title: '界面加载失败',
          message: `${errorDescription || '无法连接到 DeepTutor 界面'} (${errorCode})`,
          detail: validatedUrl,
        });
      }
    });

    contents.on('render-process-gone', (_event, details) => {
      this.logger.error(`renderer gone: ${details.reason} (exit ${details.exitCode})`);
      if (details.reason === 'clean-exit') return;
      this.showError(win, {
        title: '界面进程已退出',
        message: `渲染进程异常退出：${details.reason}`,
        detail: `exitCode=${details.exitCode}`,
        canReload: true,
      });
    });

    contents.on('preload-error', (_event, preloadPath, error) => {
      this.logger.error(`preload failed (${preloadPath}): ${error?.message || error}`);
    });

    contents.on('did-finish-load', () => {
      const url = contents.getURL();
      if (sameOrigin(url, this.service.url)) {
        this.persistUrl(url);
        // Signals to the web app (and to smoke tests) that it is running inside
        // the desktop shell rather than a tab.
        contents
          .executeJavaScript("document.documentElement.dataset.deeptutorShell = 'electron';", true)
          .catch(() => {});
      }
      this.#broadcastWindowState(win);
    });

    win.on('unresponsive', () => {
      this.logger.warn('window unresponsive');
    });

    win.on('page-title-updated', (event) => {
      event.preventDefault();
    });
  }

  #loadSplashOrApp(win) {
    if (this.service.isReady()) {
      this.loadApp(win);
      return;
    }
    const file = path.join(this.rendererDir, SPLASH_FILE);
    win.loadFile(file).catch((error) => {
      // -3/ERR_ABORTED just means the real app finished loading first.
      if (error?.code === 'ERR_ABORTED' || error?.errno === -3) return;
      this.logger.error(`splash load failed: ${error.message}`);
    });
    // The splash page shows the live service state; make sure it starts with it.
    win.webContents.once('did-finish-load', () => {
      win.webContents.send('service:status', this.service.getStatus());
    });
  }

  loadApp(win = this.mainWindow) {
    if (!win || win.isDestroyed()) return;
    const target = this.#initialUrl();
    this.logger.info(`loading app: ${target}`);
    win.loadURL(target).catch((error) => {
      if (error?.code === 'ERR_ABORTED' || error?.errno === -3) return;
      this.logger.error(`loadURL failed: ${error.message}`);
      this.showError(win, { title: '无法加载界面', message: error.message, canReload: true });
    });
  }

  #initialUrl() {
    const base = this.service.url;
    if (!this.config.get('behavior.restoreLastUrl')) return base;
    const last = this.config.get('lastUrl');
    if (!last) return base;
    try {
      const parsed = new URL(last);
      const origin = new URL(base);
      if (parsed.origin !== origin.origin) return base;
      return `${base}${parsed.pathname}${parsed.search}${parsed.hash}`;
    } catch {
      return base;
    }
  }

  showError(win, { title, message, detail, canReload = false }) {
    if (!win || win.isDestroyed()) return;
    win.__deeptutorError = true;
    const file = path.join(this.rendererDir, ERROR_FILE);
    win
      .loadFile(file, {
        query: {
          title: title || '出错了',
          message: message || '',
          detail: detail || '',
          reload: canReload ? '1' : '0',
          retry: '1',
        },
      })
      .catch((error) => this.logger.error(`error page failed: ${error.message}`));
  }

  /** Called when the service becomes ready: turn splash/error pages into the app. */
  onServiceReady() {
    for (const win of this.windows) {
      if (win.isDestroyed()) continue;
      const url = win.webContents.getURL();
      if (sameOrigin(url, this.service.url)) continue;
      this.loadApp(win);
    }
  }

  onServiceStatus(status) {
    for (const win of this.windows) {
      if (win.isDestroyed()) continue;
      win.webContents.send('service:status', status);
    }
  }

  broadcast(channel, payload) {
    for (const win of this.windows) {
      if (!win.isDestroyed()) win.webContents.send(channel, payload);
    }
  }

  #broadcastWindowState(win) {
    if (!win || win.isDestroyed()) return;
    win.webContents.send('window:state', {
      maximized: win.isMaximized(),
      fullscreen: win.isFullScreen(),
      focused: win.isFocused(),
      visible: win.isVisible(),
    });
  }

  #saveWindowState() {
    const win = this.mainWindow;
    if (!win || win.isDestroyed()) return;
    const maximized = win.isMaximized();
    const fullscreen = win.isFullScreen();
    const bounds = win.getNormalBounds ? win.getNormalBounds() : win.getBounds();
    const current = this.config.get('window');
    this.config.set({
      window: {
        ...current,
        width: bounds.width,
        height: bounds.height,
        x: bounds.x,
        y: bounds.y,
        maximized,
        fullscreen,
      },
    });
  }

  #saveLastUrl(url) {
    try {
      const parsed = new URL(url);
      this.config.set({ lastUrl: `${parsed.pathname}${parsed.search}${parsed.hash}` });
    } catch {
      /* ignore malformed */
    }
  }

  setZoom(factor) {
    const value = Math.min(3, Math.max(0.5, Number(factor) || 1));
    const current = this.config.get('window');
    this.config.set({ window: { ...current, zoomFactor: value } });
    for (const win of this.windows) {
      if (!win.isDestroyed()) win.webContents.setZoomFactor(value);
    }
    return value;
  }

  stepZoom(direction) {
    const current = this.config.get('window.zoomFactor') || 1;
    const next = Math.round((current + direction * 0.1) * 100) / 100;
    return this.setZoom(next);
  }

  toggleDevTools() {
    const win = BrowserWindow.getFocusedWindow() || this.mainWindow;
    if (!win) return;
    const contents = win.webContents;
    if (contents.isDevToolsOpened()) contents.closeDevTools();
    else contents.openDevTools({ mode: 'detach' });
  }

  toggleVisibility() {
    const win = this.mainWindow;
    if (!win || win.isDestroyed()) return this.createMainWindow();
    if (win.isVisible() && !win.isMinimized()) win.hide();
    else {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
    return win;
  }

  show() {
    const win = this.mainWindow && !this.mainWindow.isDestroyed() ? this.mainWindow : this.createMainWindow();
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
    return win;
  }

  openExternal(url) {
    if (!this.config.get('behavior.openExternalInBrowser')) {
      this.logger.info(`external open disabled: ${url}`);
      return false;
    }
    try {
      shell.openExternal(url);
      return true;
    } catch (error) {
      this.logger.warn(`openExternal failed: ${error.message}`);
      return false;
    }
  }

  confirmQuit() {
    if (!this.config.get('behavior.confirmQuit')) return true;
    const choice = dialog.showMessageBoxSync(this.mainWindow ?? undefined, {
      type: 'question',
      buttons: ['退出', '取消'],
      defaultId: 1,
      cancelId: 1,
      title: '退出 DeepTutor',
      message: '确定要退出 DeepTutor 吗？',
      detail: '本地服务（后端与界面进程）会一并停止。',
    });
    return choice === 0;
  }

  prepareQuit() {
    this.quitting = true;
    this.#saveWindowState();
    this.config.flush();
  }

  destroyAll() {
    for (const win of this.windows) {
      if (!win.isDestroyed()) win.destroy();
    }
    this.windows.clear();
    this.mainWindow = null;
  }
}

module.exports = { WindowManager };
