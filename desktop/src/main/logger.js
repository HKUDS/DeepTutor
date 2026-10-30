'use strict';

/**
 * Minimal file + memory logger for the desktop shell.
 *
 * Everything the shell does (window lifecycle, service supervision, IPC
 * failures) lands in `userData/logs/desktop-YYYY-MM-DD.log` so a user can send
 * one file when something goes wrong. The in-memory ring buffer backs the
 * "诊断信息" panel and the smoke-test report.
 */

const fs = require('node:fs');
const path = require('node:path');

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };

function pad(value) {
  return String(value).padStart(2, '0');
}

function stamp(date = new Date()) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.` +
    `${String(date.getMilliseconds()).padStart(3, '0')}`;
}

function fileStamp(date = new Date()) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

class Logger {
  constructor({ dir, level = 'info', bufferSize = 400 } = {}) {
    this.dir = dir;
    this.threshold = LEVELS[level] ?? LEVELS.info;
    this.bufferSize = bufferSize;
    this.entries = [];
    this.filePath = null;
    this.stream = null;

    if (dir) {
      try {
        fs.mkdirSync(dir, { recursive: true });
        this.filePath = path.join(dir, `desktop-${fileStamp()}.log`);
        this.stream = fs.createWriteStream(this.filePath, { flags: 'a' });
        this.stream.on('error', () => { this.stream = null; });
      } catch {
        this.stream = null;
      }
    }
  }

  setLevel(level) {
    this.threshold = LEVELS[level] ?? this.threshold;
  }

  scope(name) {
    const parent = this;
    return {
      debug: (msg) => parent.write('debug', name, msg),
      info: (msg) => parent.write('info', name, msg),
      warn: (msg) => parent.write('warn', name, msg),
      error: (msg) => parent.write('error', name, msg),
      child: (sub) => parent.scope(`${name}:${sub}`),
    };
  }

  debug(message) { this.write('debug', 'app', message); }
  info(message) { this.write('info', 'app', message); }
  warn(message) { this.write('warn', 'app', message); }
  error(message) { this.write('error', 'app', message); }

  write(level, scope, message) {
    const text = typeof message === 'string' ? message : safeStringify(message);
    const entry = { time: new Date().toISOString(), level, scope, message: text };
    this.entries.push(entry);
    if (this.entries.length > this.bufferSize) this.entries.shift();

    if ((LEVELS[level] ?? 20) < this.threshold) return;
    const line = `${stamp()} [${level.toUpperCase()}] [${scope}] ${text}`;
    if (level === 'error' || level === 'warn') console.error(line);
    else console.log(line);
    if (this.stream) this.stream.write(`${line}\n`);
  }

  /** Multi-line child-process output, tagged with its producer. */
  child(scope, chunk, streamName = 'out') {
    const text = String(chunk ?? '');
    for (const line of text.split(/\r?\n/)) {
      if (line.trim() === '') continue;
      this.write('info', `${scope}:${streamName}`, line);
    }
  }

  recent(limit = 120) {
    return this.entries.slice(-limit);
  }

  flush() {
    if (!this.stream) return;
    try { this.stream.end(); } catch { /* already closed */ }
    this.stream = null;
  }
}

function safeStringify(value) {
  if (value instanceof Error) return `${value.name}: ${value.message}\n${value.stack || ''}`;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

module.exports = { Logger, safeStringify };
