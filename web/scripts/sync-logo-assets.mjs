#!/usr/bin/env node
// Run from the source checkout: npm --prefix web run sync:logo
// sharp is installed with Next.js. Keep the approved source images untouched.
import { copyFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = path.resolve(webRoot, "../assets/figs/logo");
const publicRoot = path.join(webRoot, "public");
const targetRoot = path.join(publicRoot, "brand");
await mkdir(targetRoot, { recursive: true });

// Imagegen exports contain large transparent margins and a few nearly invisible
// pixels. Bound the visible artwork, but retain its original alpha and colors.
async function artwork(source) {
  const { data, info } = await sharp(source).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  let left = info.width, top = info.height, right = -1, bottom = -1;
  for (let y = 0; y < info.height; y++) {
    for (let x = 0; x < info.width; x++) {
      if (data[(y * info.width + x) * info.channels + info.channels - 1] <= 32) continue;
      left = Math.min(left, x);
      top = Math.min(top, y);
      right = Math.max(right, x);
      bottom = Math.max(bottom, y);
    }
  }
  if (right < left) throw new Error(`No visible logo in ${source}`);
  left = Math.max(0, left - 4);
  top = Math.max(0, top - 4);
  right = Math.min(info.width - 1, right + 4);
  bottom = Math.min(info.height - 1, bottom + 4);
  return sharp(source).extract({ left, top, width: right - left + 1, height: bottom - top + 1 });
}

for (const color of ["color", "black"]) {
  for (const kind of ["logo", "word", "full"]) {
    const name = `${color}-${kind}.png`;
    const pipeline = await artwork(path.join(sourceRoot, name));
    if (kind === "logo") {
      pipeline.resize(512, 512, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } });
    } else {
      pipeline.resize({ width: kind === "word" ? 1200 : 1600, withoutEnlargement: true });
    }
    const info = await pipeline.png().toFile(path.join(targetRoot, name));
    console.log(`${name}: ${info.width} × ${info.height}`);
  }
}

// Keep old URLs useful for images embedded in already-saved notes/documents.
for (const [alias, source] of Object.entries({
  "logo.png": "color-logo.png",
  "logo_black.png": "black-logo.png",
  "banner.png": "color-word.png",
  "logo-ver2.png": "color-logo.png",
})) {
  await copyFile(path.join(targetRoot, source), path.join(publicRoot, alias));
}

for (const [name, size] of [["favicon-16x16.png", 16], ["favicon-32x32.png", 32], ["apple-touch-icon.png", 180]]) {
  await sharp(path.join(targetRoot, "color-logo.png")).resize(size, size).png().toFile(path.join(targetRoot, name));
  await copyFile(path.join(targetRoot, name), path.join(publicRoot, name));
}
