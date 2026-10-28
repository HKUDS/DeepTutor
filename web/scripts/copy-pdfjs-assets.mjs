import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const sourceRoot = path.join(webRoot, "node_modules", "pdfjs-dist");
const targetRoot = path.join(webRoot, "public", "pdfjs");

// `wasm` backs wasmUrl (JPEG2000/JBIG2/QCMS decoders), `cmaps` backs cMapUrl
// (predefined character maps used by CID fonts).
const ASSET_DIRS = ["wasm", "cmaps"];

/**
 * Copy PDF.js decoder and character-map resources into Next's public asset tree.
 *
 * PDF.js keeps the OpenJPEG/JBIG2/QCMS WebAssembly modules and the predefined
 * CMap files outside its JS bundles and resolves them at runtime from `wasmUrl`
 * and `cMapUrl`. Next's standalone tracing does not include those package files
 * automatically, so released builds otherwise render PDFs that use JPEG2000 as
 * blank pages, and PDFs whose text uses a CID font (most CJK documents) with
 * entire runs missing.
 */
export function copyPdfjsAssets() {
  for (const assetDir of ASSET_DIRS) {
    const sourceDir = path.join(sourceRoot, assetDir);
    if (!existsSync(sourceDir)) {
      throw new Error(
        `Missing PDF.js assets at ${sourceDir}. Run npm install first.`,
      );
    }

    const targetDir = path.join(targetRoot, assetDir);
    rmSync(targetDir, { recursive: true, force: true });
    mkdirSync(targetDir, { recursive: true });
    cpSync(sourceDir, targetDir, { recursive: true });
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  copyPdfjsAssets();
}
