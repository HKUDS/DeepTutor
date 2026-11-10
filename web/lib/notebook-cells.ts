import type { NotebookCellLanguage } from "@/lib/notebook-lab-api";

/**
 * Notebook cells — the small document model behind the Notebook tab.
 *
 * A notebook is stored as plain Markdown in a Co-Writer page: fenced code
 * blocks are code cells, everything between them is Markdown prose. That keeps
 * the page readable in the note editor and searchable by the tutor, while the
 * tab parses it back into cells.
 */
export interface NotebookCell {
  id: string;
  kind: "markdown" | "code" | "geogebra";
  source: string;
  language?: NotebookCellLanguage;
  /** Learner-given name, shown above the cell's kind label. */
  name?: string;
}

export const CODE_LANGUAGES: NotebookCellLanguage[] = [
  "python",
  "shell",
  "c",
  "cpp",
];

export interface CodeLanguageLabel {
  value: NotebookCellLanguage;
  /** i18n key / English label. */
  label: string;
}

export const CODE_LANGUAGE_OPTIONS: CodeLanguageLabel[] = [
  { value: "python", label: "Python" },
  { value: "shell", label: "Shell" },
  { value: "c", label: "C" },
  { value: "cpp", label: "C++" },
];

export function normalizeCellLanguage(value: unknown): NotebookCellLanguage {
  const lang = String(value ?? "")
    .trim()
    .toLowerCase();
  if (lang === "py" || lang === "python" || lang === "python3") return "python";
  if (lang === "sh" || lang === "bash" || lang === "shell" || lang === "zsh")
    return "shell";
  if (lang === "c") return "c";
  if (lang === "cpp" || lang === "c++" || lang === "cxx" || lang === "cc")
    return "cpp";
  return "python";
}

let counter = 0;
export function newNotebookCellId(): string {
  counter += 1;
  return `cell-${Date.now().toString(36)}-${counter.toString(36)}`;
}

export function createMarkdownCell(source = ""): NotebookCell {
  return { id: newNotebookCellId(), kind: "markdown", source };
}

export function createCodeCell(
  source = "",
  language: NotebookCellLanguage = "python",
): NotebookCell {
  return { id: newNotebookCellId(), kind: "code", source, language };
}

/** A GeoGebra board cell. The source is ggbscript, one command per line. */
export function createGeogebraCell(source = ""): NotebookCell {
  return { id: newNotebookCellId(), kind: "geogebra", source };
}

function isGeogebraFence(language: string): boolean {
  const lang = language.trim().toLowerCase();
  return lang === "geogebra" || lang === "ggb";
}

/** A fresh notebook: one note cell, one code cell. */
export function defaultNotebookCells(): NotebookCell[] {
  return [createMarkdownCell(), createCodeCell()];
}

/**
 * Reorder cells by dropping one cell onto another. Moving a cell downward puts
 * it after the target; moving it upward puts it before the target.
 */
export function moveNotebookCell(
  cells: NotebookCell[],
  fromId: string,
  toId: string,
): NotebookCell[] {
  const from = cells.findIndex((cell) => cell.id === fromId);
  const to = cells.findIndex((cell) => cell.id === toId);
  if (from < 0 || to < 0 || from === to) return cells;
  const next = [...cells];
  const [moved] = next.splice(from, 1);
  const target = next.findIndex((cell) => cell.id === toId);
  next.splice(from < to ? target + 1 : target, 0, moved);
  return next;
}

const FENCE_RE = /^\s*(`{3,}|~{3,})\s*([A-Za-z0-9_+#-]*)\s*$/;

/**
 * Parse a Markdown notebook into cells. A fence at line start opens a code
 * cell; the text before it is a Markdown cell. Nested fences inside a Markdown
 * cell simply become their own cell, since the document is cell-oriented.
 */
export function parseNotebookMarkdown(markdown: string): NotebookCell[] {
  const text = String(markdown ?? "");
  if (!text.trim()) return defaultNotebookCells();

  const lines = text.split("\n");
  const cells: NotebookCell[] = [];
  let prose: string[] = [];

  const flushProse = () => {
    const source = prose.join("\n").replace(/\s+$/, "");
    if (source.trim()) cells.push(createMarkdownCell(source));
    prose = [];
  };

  let i = 0;
  while (i < lines.length) {
    const fence = FENCE_RE.exec(lines[i]);
    if (!fence) {
      prose.push(lines[i]);
      i += 1;
      continue;
    }
    const marker = fence[1][0];
    const language = fence[2] || "python";
    const body: string[] = [];
    i += 1;
    while (i < lines.length) {
      const close = FENCE_RE.exec(lines[i]);
      if (close && close[1][0] === marker) break;
      body.push(lines[i]);
      i += 1;
    }
    i += 1; // consume the closing fence
    flushProse();
    const source = body.join("\n");
    cells.push(
      isGeogebraFence(language)
        ? createGeogebraCell(source)
        : createCodeCell(source, normalizeCellLanguage(language)),
    );
  }
  flushProse();

  return cells.length ? cells : defaultNotebookCells();
}

/** Serialize cells back to Markdown, deterministically for round-trips. */
export function serializeNotebookMarkdown(cells: NotebookCell[]): string {
  const parts: string[] = [];
  for (const cell of cells) {
    if (cell.kind === "code") {
      const language = normalizeCellLanguage(cell.language);
      parts.push(`\`\`\`${language}\n${cell.source.replace(/\s+$/, "")}\n\`\`\``);
    } else if (cell.kind === "geogebra") {
      // Always emitted, even when empty, so a blank board survives a reload.
      parts.push(`\`\`\`geogebra\n${cell.source.replace(/\s+$/, "")}\n\`\`\``);
    } else if (cell.source.trim()) {
      parts.push(cell.source.replace(/\s+$/, ""));
    }
  }
  if (!parts.length) return "";
  return parts.join("\n\n").replace(/\n{3,}/g, "\n\n").concat("\n");
}
