import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const sourceDir = path.join(webRoot, "node_modules", "pdfjs-dist", "wasm");
const targetDir = path.join(webRoot, "public", "pdfjs", "wasm");

/**
 * Copy PDF.js decoder resources into Next's public asset tree.
 *
 * PDF.js keeps the OpenJPEG/JBIG2/QCMS WebAssembly modules outside its JS
 * bundles and resolves them at runtime from `wasmUrl`. Next's standalone
 * tracing does not include those package files automatically, so released
 * builds otherwise render PDFs that use JPEG2000 as blank pages.
 */
export function copyPdfjsAssets() {
  if (!existsSync(sourceDir)) {
    throw new Error(
      `Missing PDF.js decoder assets at ${sourceDir}. Run npm install first.`,
    );
  }

  rmSync(targetDir, { recursive: true, force: true });
  mkdirSync(targetDir, { recursive: true });
  cpSync(sourceDir, targetDir, { recursive: true });
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  copyPdfjsAssets();
}
