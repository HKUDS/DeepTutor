'use strict';

/**
 * Persistent, validated desktop preferences.
 *
 * The file lives in `app.getPath('userData')/config.json` and is written
 * atomically (tmp file + rename) so a crash mid-write can never leave the app
 * with a truncated config. Anything read back from disk is merged over the
 * defaults and then coerced, so a hand-edited or stale file degrades to
 * "defaults" instead of breaking the shell.
 */

const fs = require('node:fs');
const path = require('node:path');
const { EventEmitter } = require('node:events');

const SCHEMA_VERSION = 1;

const DEFAULT_CONFIG = Object.freeze({
  schemaVersion: SCHEMA_VERSION,
  window: {
    width: 1440,
    height: 920,
    x: null,
    y: null,
    maximized: false,
    fullscreen: false,
    zoomFactor: 1,
    alwaysOnTop: false,
  },
  service: {
    // Absolute path to a DeepTutor checkout/install. Empty = auto-detect.
    home: '',
    // Absolute path to the Python interpreter that can import `deeptutor`.
    pythonPath: '',
    backendPort: 8001,
    frontendPort: 3782,
    // Reuse an already-running DeepTutor instead of spawning a second stack.
    reuseRunning: true,
    autoStart: true,
    startTimeoutMs: 180000,
    extraEnv: {},
  },
  behavior: {
    closeToTray: false,
    minimizeToTray: false,
    launchAtLogin: false,
    confirmQuit: false,
    openExternalInBrowser: true,
    restoreLastUrl: true,
    openDevTools: false,
    hardwareAcceleration: true,
  },
  ui: {
    theme: 'system',
    language: 'zh-CN',
  },
  lastUrl: '',
});

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function clampNumber(value, { min, max, fallback }) {
  const num = Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.min(max, Math.max(min, num));
}

function coerceBoolean(value, fallback) {
  if (typeof value === 'boolean') return value;
  if (value === 'true' || value === 1 || value === '1') return true;
  if (value === 'false' || value === 0 || value === '0') return false;
  return fallback;
}

function coerceString(value, fallback = '') {
  if (typeof value !== 'string') return fallback;
  return value.trim();
}

function coercePort(value, fallback) {
  const num = Number(value);
  if (!Number.isInteger(num) || num < 1 || num > 65535) return fallback;
  return num;
}

/** Merge `patch` into `target`, but only along keys the schema already knows. */
function mergeKnown(target, patch) {
  if (!isPlainObject(patch)) return target;
  const out = { ...target };
  for (const [key, value] of Object.entries(patch)) {
    if (!(key in target)) continue;
    if (isPlainObject(target[key]) && isPlainObject(value)) {
      out[key] = mergeKnown(target[key], value);
    } else if (isPlainObject(target[key])) {
      continue;
    } else {
      out[key] = value;
    }
  }
  return out;
}

/** Coerce an arbitrary object into a schema-valid config. */
function normalize(raw) {
  const defaults = DEFAULT_CONFIG;
  const input = isPlainObject(raw) ? raw : {};
  const window = isPlainObject(input.window) ? input.window : {};
  const service = isPlainObject(input.service) ? input.service : {};
  const behavior = isPlainObject(input.behavior) ? input.behavior : {};
  const ui = isPlainObject(input.ui) ? input.ui : {};

  const x = Number(window.x);
  const y = Number(window.y);

  const extraEnv = {};
  if (isPlainObject(service.extraEnv)) {
    for (const [key, value] of Object.entries(service.extraEnv)) {
      if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) && (typeof value === 'string' || typeof value === 'number')) {
        extraEnv[key] = String(value);
      }
    }
  }

  return {
    schemaVersion: SCHEMA_VERSION,
    window: {
      width: Math.round(clampNumber(window.width, { min: 960, max: 10000, fallback: defaults.window.width })),
      height: Math.round(clampNumber(window.height, { min: 640, max: 10000, fallback: defaults.window.height })),
      x: Number.isFinite(x) ? Math.round(x) : null,
      y: Number.isFinite(y) ? Math.round(y) : null,
      maximized: coerceBoolean(window.maximized, false),
      fullscreen: coerceBoolean(window.fullscreen, false),
      zoomFactor: Number(clampNumber(window.zoomFactor, { min: 0.5, max: 3, fallback: 1 }).toFixed(2)),
      alwaysOnTop: coerceBoolean(window.alwaysOnTop, false),
    },
    service: {
      home: coerceString(service.home),
      pythonPath: coerceString(service.pythonPath),
      backendPort: coercePort(service.backendPort, defaults.service.backendPort),
      frontendPort: coercePort(service.frontendPort, defaults.service.frontendPort),
      reuseRunning: coerceBoolean(service.reuseRunning, true),
      autoStart: coerceBoolean(service.autoStart, true),
      startTimeoutMs: Math.round(clampNumber(service.startTimeoutMs, { min: 15000, max: 900000, fallback: 180000 })),
      extraEnv,
    },
    behavior: {
      closeToTray: coerceBoolean(behavior.closeToTray, false),
      minimizeToTray: coerceBoolean(behavior.minimizeToTray, false),
      launchAtLogin: coerceBoolean(behavior.launchAtLogin, false),
      confirmQuit: coerceBoolean(behavior.confirmQuit, false),
      openExternalInBrowser: coerceBoolean(behavior.openExternalInBrowser, true),
      restoreLastUrl: coerceBoolean(behavior.restoreLastUrl, true),
      openDevTools: coerceBoolean(behavior.openDevTools, false),
      hardwareAcceleration: coerceBoolean(behavior.hardwareAcceleration, true),
    },
    ui: {
      theme: ['system', 'light', 'dark'].includes(ui.theme) ? ui.theme : 'system',
      language: coerceString(ui.language, 'zh-CN') || 'zh-CN',
    },
    lastUrl: coerceString(input.lastUrl),
  };
}

function getPath(object, keyPath) {
  if (!keyPath) return object;
  return keyPath.split('.').reduce((node, key) => (node == null ? undefined : node[key]), object);
}

class ConfigStore extends EventEmitter {
  constructor({ filePath, logger, defaults = DEFAULT_CONFIG }) {
    super();
    this.filePath = filePath;
    this.logger = logger?.scope ? logger.scope('config') : null;
    this.defaults = defaults;
    this.data = normalize(defaults);
    this.saveTimer = null;
    this.pending = false;
  }

  load() {
    try {
      const text = fs.readFileSync(this.filePath, 'utf8');
      const parsed = JSON.parse(text);
      this.data = normalize(parsed);
      this.logger?.info(`loaded ${this.filePath}`);
    } catch (error) {
      if (error.code === 'ENOENT') {
        this.logger?.info('no config file yet, using defaults');
      } else {
        this.logger?.warn(`config unreadable (${error.message}) — resetting to defaults`);
        try {
          fs.copyFileSync(this.filePath, `${this.filePath}.corrupt`);
        } catch { /* best effort */ }
        this.data = normalize(this.defaults);
        this.scheduleSave();
      }
    }
    return this.data;
  }

  all() {
    return deepClone(this.data);
  }

  get(keyPath, fallback) {
    const value = getPath(this.data, keyPath);
    return value === undefined ? fallback : deepClone(value);
  }

  /** Shallow-merge a partial config object; returns the new full config. */
  set(patch) {
    const merged = normalize(mergeKnown(this.data, patch));
    this.data = merged;
    this.scheduleSave();
    this.emit('changed', this.all(), patch);
    return this.all();
  }

  reset() {
    this.data = normalize(this.defaults);
    this.scheduleSave();
    this.emit('changed', this.all(), this.all());
    return this.all();
  }

  scheduleSave() {
    this.pending = true;
    if (this.saveTimer) return;
    this.saveTimer = setTimeout(() => {
      this.saveTimer = null;
      this.flush();
    }, 200);
    if (typeof this.saveTimer.unref === 'function') this.saveTimer.unref();
  }

  flush() {
    if (!this.pending) return;
    this.pending = false;
    const tmp = `${this.filePath}.tmp`;
    try {
      fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
      fs.writeFileSync(tmp, `${JSON.stringify(this.data, null, 2)}\n`, 'utf8');
      fs.renameSync(tmp, this.filePath);
    } catch (error) {
      this.logger?.error(`failed to persist config: ${error.message}`);
    }
  }
}

module.exports = { ConfigStore, DEFAULT_CONFIG, normalize, SCHEMA_VERSION };
