import { readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
for (const folder of ['src', 'scripts', 'scripts/lib', 'test', ...readdirSync('platforms', { withFileTypes: true }).filter(entry => entry.isDirectory()).map(entry => path.join('platforms', entry.name))]) {
  for (const file of readdirSync(folder).filter(name => /\.(mjs|cjs|js)$/.test(name))) {
    const result = spawnSync(process.execPath, ['--check', path.join(folder, file)], { stdio: 'inherit' });
    if (result.status !== 0) process.exit(result.status ?? 1);
  }
}
