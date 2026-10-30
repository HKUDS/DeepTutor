'use strict';

/**
 * Preload bridge.
 *
 * Runs sandboxed (see webPreferences.sandbox) and exposes a *fixed* API surface
 * on `window.deeptutor`. The page can never reach ipcRenderer directly, cannot
 * invent channel names, and cannot subscribe to arbitrary events.
 */

const { contextBridge, ipcRenderer } = require('electron');

const INVOKE_CHANNELS = new Set([
  'app:info',
  'app:quit',
  'config:get',
  'config:set',
  'config:reset',
  'service:status',
  'service:restart',
  'service:openLogs',
  'service:openWorkspace',
  'shell:openExternal',
  'window:action',
  'window:state',
]);

const EVENT_CHANNELS = new Set([
  'service:status',
  'window:state',
  'config:changed',
  'menu:command',
]);

async function invoke(channel, payload) {
  if (!INVOKE_CHANNELS.has(channel)) {
    throw new Error(`通道未授权: ${channel}`);
  }
  const result = await ipcRenderer.invoke(channel, payload ?? {});
  if (result && typeof result === 'object' && 'ok' in result) {
    if (!result.ok) throw new Error(result.error || '操作失败');
    return result.data;
  }
  return result;
}

const api = {
  /** Marker so pages can adapt to the desktop shell. */
  shell: 'electron',
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
  },

  config: {
    all: () => invoke('config:get'),
    get: (key) => invoke('config:get', { key }),
    set: (patch) => invoke('config:set', { patch }),
    reset: () => invoke('config:reset'),
  },

  app: {
    info: () => invoke('app:info'),
    quit: () => invoke('app:quit'),
    openUserData: () => invoke('service:openLogs'),
    openWorkspace: () => invoke('service:openWorkspace'),
  },

  service: {
    status: () => invoke('service:status'),
    restart: () => invoke('service:restart'),
  },

  window: {
    minimize: () => ipcRenderer.send('window:action:sync', { action: 'minimize' }),
    close: () => ipcRenderer.send('window:action:sync', { action: 'close' }),
    toggleMaximize: () => invoke('window:action', { action: 'maximize' }),
    toggleFullscreen: () => invoke('window:action', { action: 'fullscreen' }),
    reload: () => invoke('window:action', { action: 'reload' }),
    openDevTools: () => invoke('window:action', { action: 'devtools' }),
    state: () => invoke('window:state'),
  },

  links: {
    open: (url) => invoke('shell:openExternal', { url }),
  },

  /**
   * Subscribe to a main-process event. Returns an unsubscribe function, and
   * never hands the raw ipcRenderer event object to the page.
   */
  on(channel, handler) {
    if (!EVENT_CHANNELS.has(channel)) throw new Error(`事件未授权: ${channel}`);
    if (typeof handler !== 'function') throw new Error('handler 必须是函数');
    const wrapped = (_event, payload) => {
      try {
        handler(payload);
      } catch (error) {
        console.error('[deeptutor] event handler failed', error);
      }
    };
    ipcRenderer.on(channel, wrapped);
    return () => ipcRenderer.removeListener(channel, wrapped);
  },
};

contextBridge.exposeInMainWorld('deeptutor', api);
