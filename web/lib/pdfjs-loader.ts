/**
 * Single place pdf.js is loaded and configured.
 *
 * The library and its worker are ~1.5 MB together, so they are imported
 * dynamically: a user who never opens the reader never downloads them. The
 * promise is memoised, so the many pages of one document share one module
 * instance and one worker.
 *
 * The worker URL is built with `new URL(..., import.meta.url)` rather than a
 * hand-written public path, which lets the bundler fingerprint and serve the
 * worker file itself — a hard-coded `/pdf.worker.mjs` would have to be copied
 * into `public/` by a build step and would break the moment the version bumps.
 *
 * Both the library and its worker are taken from the `legacy` bundle on
 * purpose. `pdfjs-dist` ships two builds: the default one is neither
 * transpiled nor polyfilled — it targets the very latest engines and calls
 * recent ECMAScript methods such as `Map.prototype.getOrInsertComputed`
 * (ES2026; Chrome/Edge 145+, Firefox 144+) straight off the platform. In any
 * older engine, including a browser or embedded webview that is merely some
 * months behind, the worker dies with
 *
 *   this._requestsByChunk.getOrInsertComputed is not a function
 *
 * and the document never renders — silently, since the failure happens in the
 * worker. The `legacy` bundle carries core-js and patches those methods in.
 * It costs roughly 100 KB more, paid only by users who actually open a PDF,
 * because this module is imported dynamically. Do not "optimise" this back to
 * the default build.
 */

import type * as PdfjsModule from "pdfjs-dist";

export type Pdfjs = typeof PdfjsModule;
export type PdfDocument = Awaited<ReturnType<Pdfjs["getDocument"]>["promise"]>;
export type PdfPageProxy = Awaited<ReturnType<PdfDocument["getPage"]>>;

const PDFJS_WASM_PATH = "/pdfjs/wasm/";

let pending: Promise<Pdfjs> | null = null;

export function loadPdfjs(): Promise<Pdfjs> {
  if (pending) return pending;
  pending = (async () => {
    const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
    if (!pdfjs.GlobalWorkerOptions.workerSrc) {
      // Must stay on the same bundle as the import above: mixing the legacy
      // library with the default worker (or vice versa) fails with
      // `The API version "a.b.c" does not match the Worker version "x.y.z"`.
      pdfjs.GlobalWorkerOptions.workerSrc = new URL(
        "pdfjs-dist/legacy/build/pdf.worker.min.mjs",
        import.meta.url,
      ).toString();
    }
    return pdfjs;
  })().catch((error) => {
    // Do not cache a failure: a transient chunk-load error must not disable the
    // reader for the rest of the session.
    pending = null;
    throw error;
  });
  return pending;
}

/** Absolute same-origin base URL used by PDF.js for decoder modules. */
export function pdfjsWasmUrl(): string {
  if (typeof window === "undefined") return PDFJS_WASM_PATH;
  return new URL(PDFJS_WASM_PATH, window.location.origin).toString();
}

/**
 * Device-pixel scale for crisp canvas rendering, bounded.
 *
 * Uncapped DPR on a 3× phone screen makes a full-page canvas large enough to be
 * dropped by mobile Safari's canvas memory limit, which shows as a blank page
 * rather than an error — hence the cap.
 */
export function outputScale(): number {
  if (typeof window === "undefined") return 1;
  return Math.min(2, Math.max(1, window.devicePixelRatio || 1));
}
