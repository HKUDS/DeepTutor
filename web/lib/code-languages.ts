/**
 * Single source of truth for code-file syntax highlighting.
 *
 * Each entry maps an attachment extension (or special filename) to the
 * Prism language name expected by ``react-syntax-highlighter``. Anything
 * listed here:
 *
 *   - is recognised as a "code" preview kind by ``previewerFor`` (so the
 *     drawer routes to ``TextPreview`` and renders inside ``RichCodeBlock``);
 *   - shows the corresponding language label in the drawer header;
 *   - assumes the backend has been taught to accept the extension via
 *     ``FileTypeRouter.TEXT_EXTENSIONS`` (deeptutor/services/rag/file_routing.py)
 *     and the frontend's ``TEXT_LIKE_EXTS`` (web/lib/doc-attachments.ts).
 *
 * Adding a new language is a one-line edit here. Adding a brand-new file
 * extension also requires the two upload-side lists above so the backend
 * doesn't reject the upload.
 */

/** Extension (lowercase, with leading dot) → Prism language name. */
export const CODE_EXT_TO_LANG: Record<string, string> = {
  // Mainstream
  ".py": "python",
  ".js": "javascript",
  ".mjs": "javascript",
  ".cjs": "javascript",
  ".ts": "typescript",
  ".mts": "typescript",
  ".cts": "typescript",
  ".jsx": "jsx",
  ".tsx": "tsx",
  ".java": "java",
  ".kt": "kotlin",
  ".kts": "kotlin",
  ".scala": "scala",
  ".groovy": "groovy",
  ".gradle": "groovy",

  // Systems
  ".c": "c",
  ".h": "c",
  ".cpp": "cpp",
  ".cc": "cpp",
  ".cxx": "cpp",
  ".hpp": "cpp",
  ".hh": "cpp",
  ".hxx": "cpp",
  ".cs": "csharp",
  ".go": "go",
  ".rs": "rust",
  ".zig": "zig",
  ".nim": "nim",

  // Apple platforms
  ".swift": "swift",
  ".m": "objectivec",
  ".mm": "objectivec",

  // Scripting
  ".rb": "ruby",
  ".php": "php",
  ".pl": "perl",
  ".pm": "perl",
  ".lua": "lua",
  ".r": "r",
  ".jl": "julia",
  ".dart": "dart",

  // Functional
  ".hs": "haskell",
  ".clj": "clojure",
  ".cljs": "clojure",
  ".cljc": "clojure",
  ".ex": "elixir",
  ".exs": "elixir",
  ".erl": "erlang",
  ".ml": "ocaml",
  ".mli": "ocaml",
  ".fs": "fsharp",
  ".fsx": "fsharp",
  ".lisp": "lisp",
  ".lsp": "lisp",
  ".scm": "scheme",
  ".rkt": "racket",

  // Web frameworks
  ".vue": "markup", // single-file component; Prism's vue plugin not always bundled — markup as a safe fallback
  ".svelte": "markup",

  // Web markup / styles
  ".html": "markup",
  ".htm": "markup",
  ".xml": "markup",
  ".css": "css",
  ".scss": "scss",
  ".sass": "sass",
  ".less": "less",
  ".sol": "solidity",

  // Shells
  ".sh": "bash",
  ".bash": "bash",
  ".zsh": "bash",
  ".fish": "bash",
  ".ps1": "powershell",
  ".vim": "vim",

  // Data / config
  ".json": "json",
  ".jsonc": "json",
  ".json5": "json",
  ".yaml": "yaml",
  ".yml": "yaml",
  ".toml": "toml",
  ".ini": "ini",
  ".cfg": "ini",
  ".properties": "ini",

  // Build / infra
  ".sql": "sql",
  ".graphql": "graphql",
  ".gql": "graphql",
  ".proto": "protobuf",
  ".cmake": "cmake",
  ".mk": "makefile",
  ".dockerfile": "docker",
  ".tf": "hcl",
  ".hcl": "hcl",
  ".nginxconf": "nginx",

  // Typesetting
  ".tex": "latex",
  ".latex": "latex",
  ".bib": "latex",
};

/**
 * Special filenames (no extension or shebang-only). Lowercase comparison.
 * Mapped before extension lookup in ``langForFilename``.
 */
const NAMED_FILES: Record<string, string> = {
  dockerfile: "docker",
  makefile: "makefile",
  cmakelists: "cmake",
  "cmakelists.txt": "cmake",
  rakefile: "ruby",
  gemfile: "ruby",
  vagrantfile: "ruby",
  "nginx.conf": "nginx",
  ".bashrc": "bash",
  ".zshrc": "bash",
  ".bash_profile": "bash",
  ".profile": "bash",
};

/** Set of all extensions covered by ``CODE_EXT_TO_LANG``. */
export const CODE_EXTS: ReadonlySet<string> = new Set(
  Object.keys(CODE_EXT_TO_LANG),
);

/**
 * Resolve a Prism language for *filename*.
 *
 * Looks at the bare filename (e.g. ``Dockerfile``) before falling back to
 * the extension. Returns ``null`` when the file is not a recognised code
 * language — callers should render it as plain monospace text.
 */
export function langForFilename(filename: string): string | null {
  if (!filename) return null;
  const lastSlash = filename.lastIndexOf("/");
  const base = (
    lastSlash >= 0 ? filename.slice(lastSlash + 1) : filename
  ).toLowerCase();
  if (NAMED_FILES[base]) return NAMED_FILES[base];

  const dotIdx = base.lastIndexOf(".");
  if (dotIdx < 0) return null;
  const ext = base.slice(dotIdx);
  return CODE_EXT_TO_LANG[ext] ?? null;
}
