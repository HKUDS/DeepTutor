/**
 * Maps a chat attachment to the preview renderer it should use.
 *
 * The drawer uses the returned ``kind`` to dynamically import the matching
 * renderer (see ``./previewers/*.tsx``). Office binaries (DOCX/XLSX/PPTX)
 * cannot be rendered natively in the browser, so we fall back to the
 * extractor's plain-text output when present, or to a download-only
 * affordance otherwise.
 */

import { langForFilename } from "@/lib/code-languages";
import { extOf } from "@/lib/doc-attachments";

export type PreviewKind =
  | "pdf"
  | "image"
  | "svg"
  | "markdown"
  | "code"
  | "text"
  | "office-text"
  | "fallback";

export interface FilePreviewSource {
  /** Display name; also used to derive the file extension. */
  filename: string;
  /** MIME type when known (image/png, application/pdf, …). */
  mimeType?: string;
  /** Backend classification — "image" or anything else. Useful for
   *  attachments where the filename has no extension but the MIME is set. */
  type?: string;
  /** Public URL served by /api/attachments. Preferred over base64. */
  url?: string;
  /** Inline base64 payload — only present for pending (un-sent) attachments
   *  or messages that pre-date the storage rollout. */
  base64?: string;
  /** Plain-text rendering of office docs, populated by the backend. */
  extractedText?: string;
  /** Original byte size, used for empty-state copy. */
  size?: number;
  /** Stable id; lets the drawer build a stable React key. */
  id?: string;
}

const OFFICE_BINARY_EXTS = new Set([".docx", ".xlsx", ".pptx"]);
const MARKDOWN_EXTS = new Set([".md", ".markdown", ".rst", ".asciidoc"]);
const PLAIN_TEXT_EXTS = new Set([
  ".txt",
  ".text",
  ".log",
  ".csv",
  ".tsv",
  ".env",
  ".conf",
]);
const RASTER_IMAGE_EXTS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".bmp",
  ".tif",
  ".tiff",
  ".avif",
]);

/** Heuristic: does *source* refer to an image we can render via <img>? */
function isImage(source: FilePreviewSource, ext: string): boolean {
  if (RASTER_IMAGE_EXTS.has(ext)) return true;
  if (
    source.mimeType?.startsWith("image/") &&
    source.mimeType !== "image/svg+xml"
  )
    return true;
  if (source.type === "image") return true;
  return false;
}

export function previewKindFor(source: FilePreviewSource): PreviewKind {
  const ext = extOf(source.filename || "");
  const mime = source.mimeType || "";

  if (ext === ".pdf" || mime === "application/pdf") return "pdf";
  if (ext === ".svg" || mime === "image/svg+xml") return "svg";
  if (isImage(source, ext)) return "image";
  if (MARKDOWN_EXTS.has(ext) || mime === "text/markdown") return "markdown";
  if (OFFICE_BINARY_EXTS.has(ext)) return "office-text";
  // Catches both extension-based mappings (.js, .ts, .go, .vue, .lua, …)
  // and special filenames without extensions (Dockerfile, Makefile, …).
  if (langForFilename(source.filename || "")) return "code";
  if (PLAIN_TEXT_EXTS.has(ext) || mime.startsWith("text/")) return "text";
  return "fallback";
}

/**
 * Build the in-browser-loadable URL for the preview, falling back to a
 * data URL when the original file lives only as base64 in memory (the
 * pending-attachment case in the composer).
 *
 * Returns ``null`` when neither is available; renderers should then show a
 * "preview not available" affordance.
 */
export function resolveSourceUrl(
  source: FilePreviewSource,
  apiUrl: (path: string) => string,
): string | null {
  if (source.url) {
    return source.url.startsWith("http") || source.url.startsWith("blob:")
      ? source.url
      : apiUrl(source.url);
  }
  if (source.base64 && source.mimeType) {
    return `data:${source.mimeType};base64,${source.base64}`;
  }
  return null;
}
