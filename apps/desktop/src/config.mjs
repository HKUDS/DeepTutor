import path from 'node:path';
import { readFile, mkdir, writeFile, rename } from 'node:fs/promises';

export const PROTOCOL_VERSION = 1;

export function localURL(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      || url.username || url.password || url.hash || url.search || url.pathname !== '/') {
    throw new Error('Expected a loopback service address such as http://127.0.0.1:3782');
  }
  return url.origin;
}

export function externalURL(value) {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password;
  } catch { return false; }
}

export function validateConfig(value) {
  if (!value || value.schemaVersion !== PROTOCOL_VERSION) throw new Error('Unsupported desktop configuration version');
  if (value.mode === 'attach') {
    return { schemaVersion: 1, mode: 'attach', url: localURL(value.url) };
  }
  if (!['source', 'bundled'].includes(value.mode)) throw new Error('Unsupported runtime mode');
  const result = { schemaVersion: 1, mode: value.mode };
  for (const name of ['sourcePath', 'pythonPath', 'nodePath', 'runtimeHome']) {
    if (typeof value[name] !== 'string' || !path.isAbsolute(value[name]) || value[name].includes('\0')) {
      throw new Error(`${name} must be an absolute path`);
    }
    result[name] = path.resolve(value[name]);
  }
  if (value.mode === 'bundled') {
    if (typeof value.webPath !== 'string' || !path.isAbsolute(value.webPath)) throw new Error('Invalid web interface path');
    result.webPath = path.resolve(value.webPath);
    result.runtimeId = String(value.runtimeId ?? '');
  }
  const relative = path.relative(result.sourcePath, result.runtimeHome);
  if (!relative || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative))) {
    throw new Error('The desktop data folder must be outside the DeepTutor source folder');
  }
  return result;
}

export async function readConfig(filename) {
  try { return validateConfig(JSON.parse(await readFile(filename, 'utf8'))); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

export async function saveConfig(filename, config) {
  const valid = validateConfig(config);
  await mkdir(path.dirname(filename), { recursive: true, mode: 0o700 });
  const temporary = `${filename}.tmp`;
  await writeFile(temporary, JSON.stringify(valid, null, 2) + '\n', { mode: 0o600 });
  await rename(temporary, filename);
  return valid;
}
