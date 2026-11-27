import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { loadTarget } from './lib/target.mjs';

// Usage: node scripts/package.mjs [--target <id>]
// Each platforms/<id>/package.mjs turns the sealed core into that platform's downloads under out/.
const target = await loadTarget();
const { default: build } = await import(pathToFileURL(path.join(target.folder, 'package.mjs')).href);
for (const file of await build(target)) console.log(file);
