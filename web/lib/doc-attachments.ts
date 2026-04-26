/**
 * Helpers for drag-and-drop document attachments in the chat composer.
 *
 * The accepted extension / MIME sets MUST stay in sync with the backend
 * `deeptutor/utils/document_extractor.py` (which in turn mirrors the KB
 * pipeline's `FileTypeRouter.TEXT_EXTENSIONS`). If you add a new format
 * server-side, add it here too.
 */

import type { LucideIcon } from "lucide-react";
import {
  Braces,
  FileCode2,
  FileImage,
  FileJson,
  FilePlus2,
  FileSpreadsheet,
  FileText,
  FileType2,
  Palette,
  Presentation,
  Settings2,
  SquareTerminal,
} from "lucide-react";

/** Binary Office formats — handled by dedicated parsers server-side. */
export const OFFICE_EXTS = [".pdf", ".docx", ".xlsx", ".pptx"] as const;

/**
 * Text-like formats — decoded server-side with multi-encoding fallback.
 * Mirrors `FileTypeRouter.TEXT_EXTENSIONS` in the Python codebase. Adding
 * a new extension here without also adding it to the backend will cause
 * the upload to be silently dropped.
 */
export const TEXT_LIKE_EXTS = [
  // Plain text & markup
  ".txt",
  ".text",
  ".log",
  ".md",
  ".markdown",
  ".rst",
  ".asciidoc",
  ".html",
  ".htm",
  ".xml",
  ".svg", // vector image, treated as XML source; rendered via <img> client-side
  // Data & config
  ".json",
  ".jsonc",
  ".json5",
  ".yaml",
  ".yml",
  ".toml",
  ".csv",
  ".tsv",
  ".ini",
  ".cfg",
  ".conf",
  ".env",
  ".properties",
  // Typesetting
  ".tex",
  ".latex",
  ".bib",
  // Stylesheets
  ".css",
  ".scss",
  ".sass",
  ".less",
  // JavaScript / TypeScript family
  ".js",
  ".mjs",
  ".cjs",
  ".ts",
  ".mts",
  ".cts",
  ".jsx",
  ".tsx",
  // Web frameworks
  ".vue",
  ".svelte",
  // Python
  ".py",
  // JVM languages
  ".java",
  ".kt",
  ".kts",
  ".scala",
  ".groovy",
  ".gradle",
  // Systems
  ".c",
  ".h",
  ".cpp",
  ".cc",
  ".cxx",
  ".hpp",
  ".hh",
  ".hxx",
  ".cs",
  ".go",
  ".rs",
  ".zig",
  ".nim",
  // Apple platforms
  ".swift",
  ".m",
  ".mm",
  // Scripting
  ".rb",
  ".php",
  ".pl",
  ".pm",
  ".lua",
  ".r",
  ".jl",
  ".dart",
  // Functional
  ".hs",
  ".clj",
  ".cljs",
  ".cljc",
  ".ex",
  ".exs",
  ".erl",
  ".ml",
  ".mli",
  ".fs",
  ".fsx",
  ".lisp",
  ".lsp",
  ".scm",
  ".rkt",
  // Smart contracts
  ".sol",
  // Shells / editors
  ".sh",
  ".bash",
  ".zsh",
  ".fish",
  ".ps1",
  ".vim",
  // Query / IDL
  ".sql",
  ".graphql",
  ".gql",
  ".proto",
  // Build / infra
  ".cmake",
  ".mk",
  ".tf",
  ".hcl",
  ".nginxconf",
  ".dockerfile",
] as const;

export const SUPPORTED_DOC_EXTS = [...OFFICE_EXTS, ...TEXT_LIKE_EXTS] as const;

export const SUPPORTED_DOC_MIMES = new Set<string>([
  // Office
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  // Common text MIMEs — browsers are inconsistent so the extension fallback
  // in classifyFile is the real workhorse.
  "text/plain",
  "text/markdown",
  "text/html",
  "text/xml",
  "application/xml",
  "application/json",
  "text/csv",
  "text/tab-separated-values",
  "text/yaml",
  "application/yaml",
  "application/x-yaml",
  "text/x-python",
  "application/x-python-code",
  "text/javascript",
  "application/javascript",
  "application/typescript",
  "text/css",
  "text/x-c",
  "text/x-c++",
  "text/x-java",
  "text/x-go",
  "text/x-rust",
  "text/x-ruby",
  "text/x-php",
  "text/x-shellscript",
  "application/sql",
  "application/toml",
]);

export const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
export const MAX_TOTAL_ATTACHMENT_BYTES = 25 * 1024 * 1024;

/**
 * `accept` attribute for the chat composer's file picker. Mirrors the formats
 * the drag-and-drop / paste paths accept (see `classifyFile`). Listing both
 * MIME types and extensions improves cross-OS reliability — Windows in
 * particular often reports an empty `File.type` for OOXML files.
 */
export const ATTACHMENT_ACCEPT = [
  "image/*",
  ...SUPPORTED_DOC_EXTS,
  ...Array.from(SUPPORTED_DOC_MIMES),
].join(",");

export type FileKind = "image" | "doc";

export function extOf(filename: string): string {
  const idx = filename.lastIndexOf(".");
  return idx >= 0 ? filename.slice(idx).toLowerCase() : "";
}

/**
 * Classify a dropped/pasted file. Returns null for unsupported types.
 *
 * SVG is classified as "doc" even though its MIME starts with `image/`, because
 * vision models reject SVG and sending the XML source lets the LLM reason about
 * the vector content. The composer still renders a thumbnail via a raw <img>
 * tag (safe — scripts inside an SVG don't run under <img> context).
 *
 * Otherwise MIME wins; extension is a fallback because browsers frequently
 * report empty `File.type` for OOXML, code, and config files.
 */
export function classifyFile(file: File): FileKind | null {
  const ext = extOf(file.name);
  if (ext === ".svg" || file.type === "image/svg+xml") return "doc";
  if (file.type && file.type.startsWith("image/")) return "image";
  if (file.type && SUPPORTED_DOC_MIMES.has(file.type)) return "doc";
  if (ext && (SUPPORTED_DOC_EXTS as readonly string[]).includes(ext))
    return "doc";
  return null;
}

/** Whether a filename refers to an SVG (case-insensitive). */
export function isSvgFilename(filename: string): boolean {
  return extOf(filename) === ".svg";
}

/**
 * Human-readable byte size: `1.2 MB`, `34.0 KB`.
 */
export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export interface DocIconSpec {
  Icon: LucideIcon;
  tint: string; // tailwind class, e.g. "text-red-500/80"
  label: string; // e.g. "PDF"
}

// Extension → icon category. Grouped so we get meaningful visual differentiation
// without carrying 50 distinct icons.
const CODE_EXTS = new Set([
  // JS/TS
  ".js",
  ".mjs",
  ".cjs",
  ".ts",
  ".mts",
  ".cts",
  ".jsx",
  ".tsx",
  ".vue",
  ".svelte",
  // Python
  ".py",
  // JVM
  ".java",
  ".kt",
  ".kts",
  ".scala",
  ".groovy",
  ".gradle",
  // Systems
  ".c",
  ".h",
  ".cpp",
  ".cc",
  ".cxx",
  ".hpp",
  ".hh",
  ".hxx",
  ".cs",
  ".go",
  ".rs",
  ".zig",
  ".nim",
  // Apple
  ".swift",
  ".m",
  ".mm",
  // Scripting
  ".rb",
  ".php",
  ".pl",
  ".pm",
  ".lua",
  ".r",
  ".jl",
  ".dart",
  // Functional
  ".hs",
  ".clj",
  ".cljs",
  ".cljc",
  ".ex",
  ".exs",
  ".erl",
  ".ml",
  ".mli",
  ".fs",
  ".fsx",
  ".lisp",
  ".lsp",
  ".scm",
  ".rkt",
  // Smart contracts
  ".sol",
]);
const SHELL_EXTS = new Set([
  ".sh",
  ".bash",
  ".zsh",
  ".fish",
  ".ps1",
  ".vim",
  ".sql",
]);
const CONFIG_EXTS = new Set([
  ".yaml",
  ".yml",
  ".toml",
  ".ini",
  ".cfg",
  ".conf",
  ".env",
  ".properties",
  ".tf",
  ".hcl",
  ".nginxconf",
  ".cmake",
  ".mk",
  ".dockerfile",
]);
const JSON_EXTS = new Set([".json", ".jsonc", ".json5"]);
const MARKUP_EXTS = new Set([
  ".md",
  ".markdown",
  ".rst",
  ".asciidoc",
  ".html",
  ".htm",
  ".xml",
  ".tex",
  ".latex",
  ".bib",
  ".graphql",
  ".gql",
  ".proto",
]);
const DATA_EXTS = new Set([".csv", ".tsv"]);
const STYLE_EXTS = new Set([".css", ".scss", ".sass", ".less"]);
const PLAIN_EXTS = new Set([".txt", ".text", ".log"]);

export function docIconFor(filename: string): DocIconSpec {
  const ext = extOf(filename);
  // Office first — keep the original distinctive colors
  switch (ext) {
    case ".pdf":
      return { Icon: FileType2, tint: "text-red-500/80", label: "PDF" };
    case ".docx":
      return { Icon: FileText, tint: "text-blue-500/80", label: "DOCX" };
    case ".xlsx":
      return {
        Icon: FileSpreadsheet,
        tint: "text-emerald-500/80",
        label: "XLSX",
      };
    case ".pptx":
      return { Icon: Presentation, tint: "text-orange-500/80", label: "PPTX" };
    case ".svg":
      return { Icon: FileImage, tint: "text-teal-500/80", label: "SVG" };
  }
  const label = ext ? ext.slice(1).toUpperCase() : "FILE";
  if (CODE_EXTS.has(ext)) {
    return { Icon: FileCode2, tint: "text-violet-500/80", label };
  }
  if (SHELL_EXTS.has(ext)) {
    return { Icon: SquareTerminal, tint: "text-slate-500/80", label };
  }
  if (JSON_EXTS.has(ext)) {
    return { Icon: FileJson, tint: "text-amber-500/80", label };
  }
  if (CONFIG_EXTS.has(ext)) {
    return { Icon: Settings2, tint: "text-slate-500/80", label };
  }
  if (STYLE_EXTS.has(ext)) {
    return { Icon: Palette, tint: "text-pink-500/80", label };
  }
  if (DATA_EXTS.has(ext)) {
    return { Icon: FileSpreadsheet, tint: "text-emerald-400/80", label };
  }
  if (MARKUP_EXTS.has(ext)) {
    return { Icon: Braces, tint: "text-sky-500/80", label };
  }
  if (PLAIN_EXTS.has(ext)) {
    return { Icon: FileText, tint: "text-[var(--muted-foreground)]", label };
  }
  // Unknown text-ish file — neutral fallback
  return {
    Icon: FilePlus2,
    tint: "text-[var(--muted-foreground)]",
    label,
  };
}
