/**
 * Utility functions for LaTeX processing
 *
 * remark-math only supports $...$ and $$...$$ delimiters by default.
 * Many LLMs output LaTeX using \(...\) and \[...\] delimiters.
 * This utility converts between formats.
 */

import { normalizeAtxHeadings } from "./markdown-display";
import {
  hasBareLatexTrigger,
  hasInlineMathCandidate,
  mapMarkdownProse,
  normalizeMathMarkup,
} from "./latex-normalize";

/**
 * Detect Markdown/LaTeX math that needs the rich KaTeX renderer.
 *
 * Display-math and backslash delimiters are detected from their opening token
 * so streaming content switches to the rich renderer as early as possible.
 * Single-dollar math and bare LaTeX are judged by the same predicates
 * `normalizeMathMarkup` uses, so routing and rendering cannot disagree — a
 * mismatch here is what made a formula render in one message and print as
 * source in the next. Once a match exists, appending streamed text cannot make
 * it disappear, so the Simple -> Rich transition remains one-way.
 */
export function hasMarkdownMath(content: string): boolean {
  if (!content) return false;
  const value = String(content);

  if (/(^|[^\\])\$\$/.test(value)) return true;
  if (/\\\(|\\\[/.test(value)) return true;
  if (hasInlineMathCandidate(value)) return true;
  return hasBareLatexTrigger(value);
}

/**
 * Normalise a model's maths into the `$...$` / `$$...$$` remark-math parses.
 *
 * Kept as the historical name because it is the published entry point, but the
 * work now lives in `latex-normalize`: as well as `\(...\)` and `\[...\]` it
 * unwraps backticked formulas, wraps bare LaTeX, and escapes the dollar signs
 * that are not delimiters — all of it skipping fenced code and code spans.
 *
 * @param content - Raw model output
 * @returns Content whose maths remark-math will read as the writer meant
 */
export function convertLatexDelimiters(content: string): string {
  if (!content) return content;

  // Rewrites insert blank lines around promoted display math; collapse the
  // runs so a formula does not tear its paragraph in half.
  return normalizeMathMarkup(String(content)).replace(/\n{3,}/g, "\n\n");
}

const LIKELY_LATEX_BLOCK_RE = /\\[A-Za-z]+|\\\\|[_^&]/;

function looksLikeLatexBlock(lines: string[]): boolean {
  const block = lines
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");

  return block.length > 0 && LIKELY_LATEX_BLOCK_RE.test(block);
}

function normalizeEditorMdInlineMath(content: string): string {
  return mapMarkdownProse(content, normalizeEditorMdInlineMathInProse);
}

function normalizeEditorMdInlineMathInProse(content: string): string {
  const lines = content.split("\n");
  const result: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed === "$" && i + 1 < lines.length) {
      let endIdx = -1;
      for (let j = i + 1; j < lines.length; j++) {
        if (lines[j].trim() === "$") {
          endIdx = j;
          break;
        }
      }

      if (endIdx > i + 1 && looksLikeLatexBlock(lines.slice(i + 1, endIdx))) {
        result.push("$$");
        for (let j = i + 1; j < endIdx; j++) {
          result.push(lines[j]);
        }
        result.push("$$");
        i = endIdx;
        continue;
      }
    }

    if (
      /^\$\$[\s\S]+\$\$$/.test(trimmed) &&
      (trimmed.match(/\$\$/g)?.length ?? 0) === 2
    ) {
      const inner = trimmed.slice(2, -2).trim();
      result.push(`$$\n${inner}\n$$`);
      continue;
    }

    // editor.md commonly uses $...$ for inline math.
    result.push(
      line.replace(/\$\$([^$\n]+?)\$\$/g, (_match, expr: string) => {
        return `$${expr.trim()}$`;
      }),
    );
  }

  return result.join("\n");
}

type HeadingEntry = {
  level: number;
  text: string;
  slug: string;
};

function slugifyHeading(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-");
}

function collectMarkdownHeadings(content: string): HeadingEntry[] {
  const lines = content.split("\n");
  const headings: HeadingEntry[] = [];
  let inFence = false;

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();

    if (/^```/.test(trimmed)) {
      inFence = !inFence;
      continue;
    }

    if (inFence) continue;

    const atxMatch = /^(#{1,6})\s+(.+?)\s*$/.exec(line);
    if (atxMatch) {
      const text = atxMatch[2].replace(/\s+#+\s*$/, "").trim();
      const slug = slugifyHeading(text);
      if (slug) headings.push({ level: atxMatch[1].length, text, slug });
      continue;
    }

    const next = lines[i + 1]?.trim();
    if (!trimmed || !next) continue;

    if (/^=+$/.test(next)) {
      const slug = slugifyHeading(trimmed);
      if (slug) headings.push({ level: 1, text: trimmed, slug });
      i += 1;
      continue;
    }

    if (/^-+$/.test(next)) {
      const slug = slugifyHeading(trimmed);
      if (slug) headings.push({ level: 2, text: trimmed, slug });
      i += 1;
    }
  }

  return headings;
}

function buildTableOfContents(headings: HeadingEntry[]): string {
  if (headings.length === 0) return "";

  return headings
    .map(({ level, text, slug }) => {
      const indent = "  ".repeat(Math.max(level - 1, 0));
      return `${indent}- [${text}](#${slug})`;
    })
    .join("\n");
}

function injectEditorMdTableOfContents(content: string): string {
  const headings = collectMarkdownHeadings(content);
  if (headings.length === 0) {
    return content.replace(/^\[TOCM?\]\s*$/gim, "");
  }

  const toc = buildTableOfContents(headings);
  return content.replace(/^\[TOCM?\]\s*$/gim, toc);
}

export function convertFlowFenceToMermaid(source: string): string | null {
  const lines = source
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (lines.length === 0) return null;

  const nodeDefs: string[] = [];
  const edges: string[] = [];

  const renderNode = (id: string, type: string, label: string): string => {
    const safeLabel = label.replace(/\|/g, "\\|");
    switch (type) {
      case "start":
      case "end":
        return `${id}([${safeLabel}])`;
      case "condition":
        return `${id}{${safeLabel}}`;
      case "inputoutput":
        return `${id}[/${safeLabel}/]`;
      case "subroutine":
        return `${id}[[${safeLabel}]]`;
      case "database":
        return `${id}[(${safeLabel})]`;
      default:
        return `${id}[${safeLabel}]`;
    }
  };

  for (const line of lines) {
    const defMatch =
      /^([A-Za-z][\w-]*)(?:=>|=)(start|end|operation|condition|inputoutput|subroutine|database):\s*(.+)$/.exec(
        line,
      );

    if (defMatch) {
      const [, id, type, label] = defMatch;
      nodeDefs.push(`  ${renderNode(id, type, label)}`);
      continue;
    }

    if (!line.includes("->")) continue;

    const parts = line
      .split("->")
      .map((part) => part.trim())
      .filter(Boolean);
    for (let i = 0; i < parts.length - 1; i += 1) {
      const fromMatch = /^([A-Za-z][\w-]*)(?:\(([^)]+)\))?$/.exec(parts[i]);
      const toMatch = /^([A-Za-z][\w-]*)(?:\(([^)]+)\))?$/.exec(parts[i + 1]);
      if (!fromMatch || !toMatch) continue;

      const [, fromId, fromAnnotation] = fromMatch;
      const [, toId] = toMatch;
      // flowchart.js puts branch labels on the source side (`cond(yes)->x`);
      // pure layout hints (`op(right)->x`) are not labels.
      const branch = fromAnnotation?.split(",")[0]?.trim();
      const label =
        branch && !/^(left|right|top|bottom)$/i.test(branch)
          ? `|${branch}|`
          : "";
      edges.push(`  ${fromId} -->${label} ${toId}`);
    }
  }

  if (nodeDefs.length === 0 || edges.length === 0) return null;
  return ["flowchart TD", ...nodeDefs, ...edges].join("\n");
}

export function convertSequenceFenceToMermaid(source: string): string | null {
  const lines = source
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (lines.length === 0) return null;

  const isSequenceDirective = (line: string): boolean => {
    return (
      /^Note\s+(left|right)\s+of\s+/i.test(line) ||
      /^participant\s+/i.test(line) ||
      /^(title|autonumber|activate|deactivate|loop|rect|opt|alt|par|critical|break|box|create|destroy)\b/i.test(
        line,
      ) ||
      /^([A-Za-z][\w.-]*)(?:-{1,2}>>?|--?>)([A-Za-z][\w.-]*)\s*:\s*.+$/.test(
        line,
      )
    );
  };

  const normalizedLines: string[] = [];
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];

    if (/^Note\s+(left|right)\s+of\s+/i.test(line)) {
      let combined = line;

      while (i + 1 < lines.length && !isSequenceDirective(lines[i + 1])) {
        combined += `\\n${lines[i + 1]}`;
        i += 1;
      }

      normalizedLines.push(combined);
      continue;
    }

    normalizedLines.push(line);
  }

  const converted = normalizedLines.map((line) => {
    if (/^Note\s+(left|right)\s+of\s+/i.test(line)) {
      return `  ${line.replace(/\\n/g, "<br/>")}`;
    }

    const messageMatch =
      /^([A-Za-z][\w.-]*)(-{1,2}>>?|--?>)([A-Za-z][\w.-]*)\s*:\s*(.+)$/.exec(
        line,
      );

    if (messageMatch) {
      const [, from, operator, to, message] = messageMatch;
      const arrow =
        operator === "--" || operator === "-->"
          ? "-->>"
          : operator === "->>" || operator === "-->>"
            ? operator
            : "->>";
      return `  ${from}${arrow}${to}: ${message}`;
    }

    return `  ${line}`;
  });

  return ["sequenceDiagram", ...converted].join("\n");
}

function convertEditorMdFences(content: string): string {
  return content.replace(
    /```(flow|seq|sequence)\s*\n([\s\S]*?)```/g,
    (_match, lang: string, body: string) => {
      const converted =
        lang === "flow"
          ? convertFlowFenceToMermaid(body)
          : convertSequenceFenceToMermaid(body);

      if (!converted) return `\`\`\`${lang}\n${body}\`\`\``;
      return `\`\`\`mermaid\n${converted}\n\`\`\``;
    },
  );
}

/**
 * Process content for ReactMarkdown rendering with proper LaTeX support
 * This is a convenience wrapper that applies all necessary transformations.
 *
 * @param content - The raw content to process
 * @returns Processed content ready for ReactMarkdown with remark-math
 */
export function processLatexContent(content: string): string {
  if (!content) return "";

  // Convert to string if not already
  const str = String(content);

  return normalizeMathMarkup(str);
}

export function processMarkdownContent(content: string): string {
  if (!content) return "";

  let result = String(content);
  result = normalizeAtxHeadings(result);
  result = normalizeEditorMdInlineMath(result);
  result = convertEditorMdFences(result);
  result = injectEditorMdTableOfContents(result);
  result = normalizeMathMarkup(result);
  result = result.replace(/\n{3,}/g, "\n\n");

  return result;
}
