import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

// Usage (macOS): node scripts/make-ico.mjs assets/icon.icns assets/icon.ico
// Renders the macOS icon at the Windows sizes and stores them as PNG entries.
const [input, output] = process.argv.slice(2);
const sizes = [16, 24, 32, 48, 64, 128, 256];
const work = await mkdtemp(path.join(os.tmpdir(), 'open-deeptutor-ico-'));
try {
  const images = [];
  for (const size of sizes) {
    const file = path.join(work, `${size}.png`);
    execFileSync('/usr/bin/sips', ['-s', 'format', 'png', '-z', String(size), String(size), input, '--out', file], { stdio: 'ignore' });
    images.push({ size, data: await readFile(file) });
  }
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach(({ size, data }, index) => {
    const entry = 6 + 16 * index;
    header.writeUInt8(size % 256, entry); // 0 means 256
    header.writeUInt8(size % 256, entry + 1);
    header.writeUInt16LE(1, entry + 4);
    header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(data.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += data.length;
  });
  await writeFile(output, Buffer.concat([header, ...images.map(image => image.data)]));
} finally {
  await rm(work, { recursive: true, force: true });
}
