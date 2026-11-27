/**
 * Quiz math normalisation — the browser-side mirror of
 * `deeptutor/core/assessment.py:normalize_math_delimiters`.
 *
 * Book quiz payloads are rendered by `QuizBlock` through `MarkdownRenderer`,
 * which uses remark-math + rehype-katex. That pipeline only understands
 * `$...$` / `$$...$$`, and a fill-in-the-blank marker made of underscores
 * inside a formula (`= \;____`) is a hard KaTeX parse error. rehype-katex then
 * degrades to a visible `katex-error` span, which is the "raw LaTeX on the
 * page" symptom. Normalise before rendering so payloads written before the
 * backend fix still display correctly.
 *
 * `normalizeMathMarkup` already handles bare command sequences and
 * `\(...\)` / `\[...\]`; this module adds the two quiz-specific repairs:
 * script-only expressions (`x^{2}`) and underscore blanks inside maths.
 */

import { mapMarkdownProse, normalizeMathMarkup } from "./latex-normalize";

const MATH_SPAN_RE =
  /\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\\)\$(?:\\.|[^$\n])*?(?<!\\)\$/g;
const BLANK_RUN_RE = /(?<!\\)_{2,}/g;
const BLANK_REPLACEMENT = "\\underline{\\hspace{2em}}";
// `x^{2}`, `a_{n}`, `f(x)^{2}` — a script expression with no `\command` in it,
// so `normalizeMathMarkup` has no trigger to notice.
const BARE_SCRIPT_RE =
  /(?<![\w$\\])([A-Za-z](?:[0-9]+|\([^()\n]*\))?(?:\^\{[^{}\n]*\}|_\{[^{}\n]*\})+(?:[+\-*/=][A-Za-z0-9()]+(?:\^\{[^{}\n]*\}|_\{[^{}\n]*\})*)*)/g;
const INLINE_CODE_RE = /`[^`\n]+`/g;
const PLACEHOLDER_RE = /@@DTQM(\d+)@@/g;
const MATH_WORDS = new Set([
  "sin",
  "cos",
  "tan",
  "cot",
  "sec",
  "csc",
  "log",
  "exp",
  "lim",
  "max",
  "min",
  "sup",
  "inf",
  "det",
  "dim",
  "gcd",
  "lcm",
  "mod",
  "arg",
]);
const CJK_RE =
  /[぀-ヿ㐀-䶿一-鿿가-힯]|[、。，；：？！（）《》「」【】…—]/u;

/** Would this dollar-delimited body be a formula rather than currency? */
function plausibleInlineMath(body: string): boolean {
  const value = body.trim();
  if (!value || value.length > 400 || value.includes("\n\n")) return false;
  if (/\\[A-Za-z]+|[\^_]|\\\\/.test(value)) return true;

  const tight = !/^\s/.test(body) && !/\s$/.test(body);
  if (CJK_RE.test(value)) {
    return tight && value.length <= 40 && /[=+\-*/<>]/.test(value);
  }

  if (value.length > 60) return false;
  const words = value.match(/[A-Za-z]{3,}/g) ?? [];
  return words.every((word) => MATH_WORDS.has(word.toLowerCase()));
}

/**
 * A run of underscores inside `$...$` is not a blank to KaTeX — the first `_`
 * demands a subscript group and the parse fails. Replace it with an underlined
 * horizontal space. Blank runs outside maths are prose and stay untouched.
 */
export function sanitizeMathBlanks(text: string): string {
  if (!text) return text;
  return text.replace(MATH_SPAN_RE, (span) => {
    if (span.startsWith("$") && !span.startsWith("$$")) {
      const body = span.slice(1, -1);
      if (!plausibleInlineMath(body)) return span;
      return `$${body.trim().replace(BLANK_RUN_RE, BLANK_REPLACEMENT)}$`;
    }
    return span.replace(BLANK_RUN_RE, BLANK_REPLACEMENT);
  });
}

/**
 * Wrap script-only expressions such as `x^{2}` that carry no LaTeX command.
 * Maths spans and code spans are masked first so nothing is wrapped twice.
 */
export function wrapBareScriptExpressions(text: string): string {
  if (!text) return text;
  return mapMarkdownProse(text, (prose) => {
    const stored: string[] = [];
    const masked = prose.replace(
      new RegExp(`${INLINE_CODE_RE.source}|${MATH_SPAN_RE.source}`, "g"),
      (match) => {
        stored.push(match);
        return `@@DTQM${stored.length - 1}@@`;
      },
    );
    const wrapped = masked.replace(BARE_SCRIPT_RE, (_match, fragment: string) => {
      return `$${fragment}$`;
    });
    return wrapped.replace(
      PLACEHOLDER_RE,
      (_match, index: string) => stored[Number(index)] ?? "",
    );
  });
}

/**
 * Normalise a single quiz field for the KaTeX renderer. Idempotent.
 */
export function normalizeQuizMathText(text: string): string {
  if (!text) return text;
  const normalized = normalizeMathMarkup(String(text));
  return sanitizeMathBlanks(wrapBareScriptExpressions(normalized));
}