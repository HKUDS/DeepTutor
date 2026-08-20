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
 */

import type * as PdfjsModule from "pdfjs-dist";

export type Pdfjs = typeof PdfjsModule;
export type PdfDocument = Awaited<ReturnType<Pdfjs["getDocument"]>["promise"]>;
export type PdfPageProxy = Awaited<ReturnType<PdfDocument["getPage"]>>;

let pending: Promise<Pdfjs> | null = null;

export function loadPdfjs(): Promise<Pdfjs> {
  if (pending) return pending;
  pending = (async () => {
    const pdfjs = await import("pdfjs-dist");
    if (!pdfjs.GlobalWorkerOptions.workerSrc) {
      pdfjs.GlobalWorkerOptions.workerSrc = new URL(
        "pdfjs-dist/build/pdf.worker.min.mjs",
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
