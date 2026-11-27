import { SourceRuntime } from './runtime.mjs';
import { createWriteStream } from 'node:fs';
import { mkdir, stat, rename } from 'node:fs/promises';
import path from 'node:path';

let runtime;
let log;
let stopping = false;
function send(value) { if (process.connected) process.send(value); }

async function stop() {
  if (stopping) return;
  stopping = true;
  await runtime?.stop();
  log?.end();
  process.exit(0);
}

process.on('message', async message => {
  if (message.type === 'stop') return void stop();
  if (message.type !== 'start' || runtime || stopping) return;
  try {
    await mkdir(path.dirname(message.logPath), { recursive: true, mode: 0o700 });
    if (stopping) return;
    const size = await stat(message.logPath).then(s => s.size).catch(() => 0);
    if (size > 10 * 1024 * 1024) await rename(message.logPath, `${message.logPath}.previous`);
    log = createWriteStream(message.logPath, { flags: 'a', mode: 0o600 });
    log.on('error', error => { send({ phase: 'error', message: error.message }); void stop(); });
    log.write(`\n--- Desktop runtime ${new Date().toISOString()} ---\n`);
    runtime = new SourceRuntime({ log: chunk => log.write(chunk) });
    runtime.on('status', send);
    await runtime.start(message.config, message.cachePath);
  } catch (error) {
    send({ phase: 'error', message: error.message });
    await runtime?.stop();
  }
});
process.on('disconnect', () => void stop());
for (const signal of ['SIGTERM', 'SIGINT', 'SIGHUP']) process.on(signal, () => void stop());
