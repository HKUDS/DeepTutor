/**
 * Turn the maths an LLM actually writes into the maths remark-math can parse.
 *
 * Nothing in the product tells a model which delimiters to use, so one answer
 * arrives as `$x$`, the next as `\(x\)`, the next with the formula in a code
 * span, and the next with no delimiters at all. remark-math only understands
 * `$...$` and `$$...$$`, so everything else reached the reader as raw source —
 * "the LaTeX didn't render". At the same time remark-math's `$` rule is loose
 * enough to swallow prose ("$5 and $10" renders as one formula, both dollar
 * signs gone), which is the same bug seen from the other side — "the $$ got
 * eaten".
 *
 * This module is the single place that reconciles the two. It runs before the
 * markdown parser and leaves behind only `$...$` / `$$...$$` spans remark-math
 * will read the way the writer meant, with every other `$` escaped so it stays
 * a dollar sign.
 *
 * Everything here is deliberately conservative: code blocks and code spans are
 * masked before any rewrite, a bare fragment is only wrapped when every
 * backslash token in it is a control sequence KaTeX knows, and an ambiguous
 * `$` is left as text rather than guessed into a formula.
 */

import { isKnownLatexCommand, isMathTriggerCommand } from "./latex-commands";

const FENCE_LINE_RE = /^ {0,3}(`{3,}|~{3,})/;
const INLINE_CODE_SPAN_RE = /(`+)([^`\n]+?)\1/g;
// `$$...$$` first so a display span is never split into two inline ones.
const MATH_SPAN_RE = /\$\$[\s\S]*?\$\$|\$(?!\s)(?:\\.|[^$\n])*?(?<!\s)\$/g;
const CJK_RE =
  /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]|[，。、；：？！（）《》「」【】…—]/u;
const LATEX_STRUCTURE_RE = /\\[a-zA-Z]+|[\^_]|\\\\/;
// Function names a writer may legitimately spell out inside a formula.
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

// ---------------------------------------------------------------------------
// masking
// ---------------------------------------------------------------------------

// A printable sentinel rather than a control character: masked text passes
// through regexes, `split`/`join` and (during debugging) the console, and a
// stray placeholder is legible in the output instead of invisible.
const MASK_PREFIX = "@@DTMASK";
const MASK_SUFFIX = "@@";

type Mask = {
  masked: string;
  restore: (value: string) => string;
};

function maskSpans(content: string, regex: RegExp, label: string): Mask {
  const spans: string[] = [];
  const masked = content.replace(regex, (match) => {
    spans.push(match);
    return `${MASK_PREFIX}${label}${spans.length - 1}${MASK_SUFFIX}`;
  });
  const placeholder = new RegExp(
    `${MASK_PREFIX}${label}(\\d+)${MASK_SUFFIX}`,
    "g",
  );
  return {
    masked,
    restore: (value: string) =>
      value.replace(placeholder, (_m, idx: string) => spans[Number(idx)] ?? ""),
  };
}

/**
 * Run a transform over the prose of a markdown document, leaving every fenced
 * code block byte-for-byte intact.
 *
 * Without this a tutorial *about* LaTeX had its own examples rewritten — a
 * ```tex fence containing a `\(x+y\)` sample came out as ` $x+y$ `.
 */
export function mapMarkdownProse(
  content: string,
  transform: (text: string) => string,
): string {
  if (!content.includes("```") && !content.includes("~~~")) {
    return transform(content);
  }

  const lines = content.split("\n");
  const out: string[] = [];
  let prose: string[] = [];
  let fence: string | null = null;

  const flush = () => {
    if (prose.length === 0) return;
    out.push(transform(prose.join("\n")));
    prose = [];
  };

  for (const line of lines) {
    const marker = FENCE_LINE_RE.exec(line)?.[1];

    if (fence) {
      out.push(line);
      if (marker && marker[0] === fence[0] && marker.length >= fence.length) {
        fence = null;
      }
      continue;
    }

    if (marker) {
      flush();
      out.push(line);
      fence = marker;
      continue;
    }

    prose.push(line);
  }

  flush();
  return out.join("\n");
}

// ---------------------------------------------------------------------------
// is this maths?
// ---------------------------------------------------------------------------

/** Every `\word` in the fragment is a control sequence KaTeX understands. */
function commandsAreKnown(fragment: string): boolean {
  for (const match of fragment.matchAll(/\\([a-zA-Z]+)/g)) {
    if (!isKnownLatexCommand(match[1])) return false;
  }
  return true;
}

function hasTriggerCommand(fragment: string): boolean {
  for (const match of fragment.matchAll(/\\([a-zA-Z]+)/g)) {
    if (isMathTriggerCommand(match[1])) return true;
  }
  return false;
}

function bracesBalanced(fragment: string): boolean {
  let depth = 0;
  for (let i = 0; i < fragment.length; i += 1) {
    if (fragment[i] === "\\") {
      i += 1;
      continue;
    }
    if (fragment[i] === "{") depth += 1;
    else if (fragment[i] === "}") {
      depth -= 1;
      if (depth < 0) return false;
    }
  }
  return depth === 0;
}

/**
 * Would this body, if it were between delimiters, be a formula rather than
 * prose that happens to sit between two dollar signs?
 *
 * `tight` is remark-math's own shape test (no space just inside the
 * delimiters). A loose body has to work harder to be believed, because a loose
 * `$` is overwhelmingly currency.
 */
function plausibleMathBody(body: string, tight: boolean): boolean {
  const value = body.trim();
  if (!value || value.length > 400 || value.includes("\n\n")) return false;
  if (value.includes(MASK_PREFIX)) return false;

  // Real LaTeX structure settles it, either way round.
  if (LATEX_STRUCTURE_RE.test(value)) return commandsAreKnown(value);

  if (value.length > 60) return false;

  if (CJK_RE.test(value)) {
    // "速度 = 路程/时间" is a formula a Chinese tutor writes; "5 和 " is the gap
    // between two prices. Require the shape of an equation, tightly delimited,
    // and keep it short.
    return tight && value.length <= 40 && /[=+\-*/<>]/.test(value);
  }

  // Latin prose gives itself away with words. `x + y`, `f(x)` and `E = mc` are
  // all formulas; "5 and the value of " is not.
  const words = value.match(/[A-Za-z]{3,}/g) ?? [];
  return words.every((word) => MATH_WORDS.has(word.toLowerCase()));
}

/**
 * `A+BC=(A+B)(A+C)` — an expression with no LaTeX command in it at all, so
 * nothing in the string itself distinguishes maths from a line of code.
 *
 * Only consulted when the surrounding document already contains real maths:
 * in a page about Boolean algebra a backticked `A + AB = A` is a formula, and
 * leaving it in a monospace box next to three rendered siblings looks more
 * broken than leaving all four unrendered.
 */
function looksLikePlainMathExpression(value: string): boolean {
  if (value.length > 60) return false;
  if (!/^[A-Za-z0-9+\-*/=^_(){}[\]., <>|']+$/.test(value)) return false;
  if (!/[+\-*/=]/.test(value)) return false;
  // Operators that only exist in programming languages.
  if (/[=!<>]=|=>|->|&&|\|\||\+\+|--|\/\//.test(value)) return false;
  // `a[i]` is a subscript in code; maths writes `a_i`.
  if (/\[[A-Za-z_][A-Za-z0-9_]*\]/.test(value)) return false;
  // `MAX_LEN` is an identifier; `a_1` is a subscript.
  if (/[A-Za-z]{2,}_[A-Za-z]{2,}/.test(value)) return false;

  // Multi-letter runs are variables juxtaposed for multiplication (`AB`, `BCD`)
  // or named functions — never lowercase words like `npm run dev`.
  const words = value.match(/[A-Za-z]{2,}/g) ?? [];
  return words.every(
    (word) =>
      MATH_WORDS.has(word.toLowerCase()) ||
      (word.length <= 4 && word === word.toUpperCase()),
  );
}

/** A code span whose contents are a formula, not code. */
function backtickedLatex(inner: string, mathContext: boolean): string | null {
  const value = inner.trim();
  if (!value || value.includes(MASK_PREFIX)) return null;

  // The model wrapped an already-delimited formula in backticks.
  const displayWrapped = /^\$\$([\s\S]+)\$\$$/.exec(value);
  if (displayWrapped) return `$$${displayWrapped[1].trim()}$$`;
  const inlineWrapped = /^\$([^$]+)\$$/.exec(value);
  if (inlineWrapped) return `$${inlineWrapped[1].trim()}$`;

  // Bare LaTeX in a code span — `\overline{A+B}=\bar{A}\bar{B}`. Demanding a
  // trigger command keeps `$PATH`, `npm run dev` and `a[i] = b` as code.
  if (value.includes("$")) return null;
  if (!hasTriggerCommand(value)) {
    return mathContext && looksLikePlainMathExpression(value)
      ? `$${value}$`
      : null;
  }
  if (!commandsAreKnown(value) || !bracesBalanced(value)) return null;
  return `$${value}$`;
}

// ---------------------------------------------------------------------------
// delimiter conversion
// ---------------------------------------------------------------------------

/**
 * `\\(x\\)` — a JSON escape that survived one decode too few. Only rewritten
 * when both halves are doubled, so a genuine `\\` line break is left alone.
 */
function normalizeDoubledDelimiters(text: string): string {
  let result = text;
  if (/\\\\\(/.test(result) && /\\\\\)/.test(result)) {
    result = result.replace(/\\\\([()])/g, "\\$1");
  }
  if (/\\\\\[/.test(result) && /\\\\\]/.test(result)) {
    result = result.replace(/\\\\([[\]])/g, "\\$1");
  }
  return result;
}

/**
 * `\[` and `\]` are also CommonMark's escapes for literal square brackets, so
 * a bare reference marker `\[1\]` arrives looking exactly like display math.
 * Demand more than a plausible body: real structure, or at least an operator
 * joining two terms.
 */
function looksLikeDisplayMath(body: string): boolean {
  if (!plausibleMathBody(body, true)) return false;
  if (LATEX_STRUCTURE_RE.test(body)) return true;
  return /[=+\-*/<>]/.test(body) && /[A-Za-z0-9]/.test(body);
}

function convertBracketDelimiters(text: string): string {
  return text.replace(/\\\[([\s\S]*?)\\\]/g, (match, expr: string) => {
    const body = expr.trim();
    if (!looksLikeDisplayMath(body)) return match;
    return `\n$$\n${body}\n$$\n`;
  });
}

function convertParenDelimiters(text: string): string {
  return text
    .split("\n")
    .map((line) => {
      // Inside a table row a greedy `\(a | b\)` would merge two cells.
      const pattern = /^\s*\|/.test(line)
        ? /\\\(([^\n|]*?)\\\)/g
        : /\\\(([^\n]*?)\\\)/g;
      return line.replace(pattern, (match, expr: string) => {
        const body = expr.trim();
        if (!body || body.includes("$")) return match;
        return `$${body}$`;
      });
    })
    .join("\n");
}

// ---------------------------------------------------------------------------
// bare LaTeX
// ---------------------------------------------------------------------------

const MATH_PUNCTUATION = new Set([
  "+",
  "-",
  "*",
  "/",
  "=",
  "^",
  "_",
  "<",
  ">",
  "(",
  ")",
  "[",
  "]",
  ",",
  ".",
  "!",
  "'",
  ":",
  ";",
]);

/**
 * After a space, does the formula continue? An operator, a digit, a control
 * sequence or a lone variable keeps it going; an English word ends it, so
 * `\alpha is large` wraps only `\alpha`.
 */
function continuesAfterSpace(line: string, spaceIndex: number): boolean {
  const next = line[spaceIndex + 1];
  if (!next) return false;
  if (next === "\\") {
    const cmd = /^\\([a-zA-Z]+)/.exec(line.slice(spaceIndex + 1));
    return !cmd || isKnownLatexCommand(cmd[1]);
  }
  if (/[0-9]/.test(next)) return true;
  if ("+-*/=^_<>".includes(next)) return true;
  if (/[A-Za-z]/.test(next)) {
    const after = line[spaceIndex + 2];
    return !after || !/[A-Za-z]/.test(after);
  }
  return false;
}

function scanFragmentEnd(
  line: string,
  start: number,
  stopAtPipe: boolean,
): number {
  let i = start;
  let depth = 0;

  while (i < line.length) {
    const ch = line[i];

    if (ch === "\\") {
      const cmd = /^\\([a-zA-Z]+)/.exec(line.slice(i));
      if (cmd) {
        if (!isKnownLatexCommand(cmd[1])) break;
        i += cmd[0].length;
        continue;
      }
      // `\{`, `\\`, `\,` — an escaped single character.
      if (i + 1 >= line.length) break;
      i += 2;
      continue;
    }

    if (ch === "{") {
      depth += 1;
      i += 1;
      continue;
    }
    if (ch === "}") {
      if (depth === 0) break;
      depth -= 1;
      i += 1;
      continue;
    }

    // Inside a group anything goes — `\text{速度}` is legitimate.
    if (depth > 0) {
      if (ch === "`" || ch === "$" || ch === "|" || ch === "@") break;
      i += 1;
      continue;
    }

    if (/[A-Za-z0-9]/.test(ch) || MATH_PUNCTUATION.has(ch)) {
      i += 1;
      continue;
    }
    if (ch === "|") {
      if (stopAtPipe) break;
      i += 1;
      continue;
    }
    if (ch === " ") {
      if (!continuesAfterSpace(line, i)) break;
      i += 1;
      continue;
    }
    break;
  }

  if (depth !== 0) return start;
  // Trailing sentence punctuation belongs to the prose, not the formula.
  while (i > start && " ,.;:!".includes(line[i - 1])) i -= 1;
  return i;
}

/** `2\pi` — a coefficient written straight onto the command. */
function scanFragmentStart(line: string, commandIndex: number): number {
  let i = commandIndex;
  while (i > 0 && /[0-9]/.test(line[i - 1])) i -= 1;
  return i;
}

function wrapBareLatexInLine(line: string): string {
  if (!line.includes("\\")) return line;

  const stopAtPipe = /^\s*\|/.test(line);
  let out = "";
  let i = 0;

  while (i < line.length) {
    if (line[i] !== "\\") {
      out += line[i];
      i += 1;
      continue;
    }

    const cmd = /^\\([a-zA-Z]+)/.exec(line.slice(i));
    if (!cmd || !isMathTriggerCommand(cmd[1])) {
      const width = cmd ? cmd[0].length : 2;
      out += line.slice(i, i + width);
      i += width;
      continue;
    }

    const start = scanFragmentStart(line, i);
    const end = scanFragmentEnd(line, i, stopAtPipe);
    const fragment = line.slice(start, end);

    if (
      end <= i ||
      fragment.includes("$") ||
      fragment.includes("`") ||
      fragment.includes(MASK_PREFIX) ||
      !commandsAreKnown(fragment) ||
      !bracesBalanced(fragment)
    ) {
      out += cmd[0];
      i += cmd[0].length;
      continue;
    }

    out = out.slice(0, out.length - (i - start)) + `$${fragment}$`;
    i = end;
  }

  return out;
}

/**
 * `\begin{aligned} ... \end{aligned}` written with no delimiters around it —
 * common from models that assume the host renders full LaTeX.
 */
function wrapBareEnvironments(text: string): string {
  return text.replace(/\\begin\{([a-zA-Z*]+)\}[\s\S]*?\\end\{\1\}/g, (match) =>
    commandsAreKnown(match) ? `\n$$\n${match.trim()}\n$$\n` : match,
  );
}

function wrapBareLatex(text: string): string {
  // Promoting an environment creates a `$$` block of its own; mask it before
  // the per-line pass or `\begin{aligned}` gets wrapped a second time, as
  // `$\begin{aligned}$`, and KaTeX is handed an environment with no body.
  const promoted = maskSpans(wrapBareEnvironments(text), MATH_SPAN_RE, "ENV");
  return promoted.restore(
    promoted.masked.split("\n").map(wrapBareLatexInLine).join("\n"),
  );
}

// ---------------------------------------------------------------------------
// stray dollars
// ---------------------------------------------------------------------------

/**
 * Escape every `$` that is not delimiting a formula.
 *
 * remark-math pairs dollar signs greedily across a line, so "$5 and $10"
 * renders as the formula "5 and " with both dollars consumed. Left alone that
 * is silent data loss, and it only bites the messages that happen to take the
 * rich renderer — which is why it reads as random.
 */
function escapeStrayDollars(text: string): string {
  let out = "";
  let i = 0;

  while (i < text.length) {
    const ch = text[i];

    if (ch === "\\") {
      out += text.slice(i, i + 2);
      i += 2;
      continue;
    }

    if (ch !== "$") {
      out += ch;
      i += 1;
      continue;
    }

    if (text.startsWith("$$", i)) {
      const close = text.indexOf("$$", i + 2);
      if (close === -1) {
        // Still streaming, or genuinely unbalanced: leave it as written.
        out += text.slice(i);
        break;
      }
      out += text.slice(i, close + 2);
      i = close + 2;
      continue;
    }

    const lineEnd = text.indexOf("\n", i + 1);
    const limit = lineEnd === -1 ? text.length : lineEnd;
    const close = text.indexOf("$", i + 1);

    if (close === -1 || close > limit) {
      // No partner on this line. A lone `$` is currency more often than an
      // unfinished formula, but escaping one mid-stream would flash a
      // backslash at the reader, so leave it: remark-math needs the pair too.
      out += "$";
      i += 1;
      continue;
    }

    const body = text.slice(i + 1, close);
    const tight = !/^\s/.test(body) && !/\s$/.test(body);

    if (!plausibleMathBody(body, tight)) {
      out += "\\$";
      i += 1;
      continue;
    }

    out += `$${body.trim()}$`;
    i = close + 1;
  }

  return out;
}

// ---------------------------------------------------------------------------
// entry points
// ---------------------------------------------------------------------------

function normalizeProse(text: string, mathContext: boolean): string {
  // Unwrap first: this is the one step that reads code spans rather than
  // hiding them.
  let result = text.replace(
    INLINE_CODE_SPAN_RE,
    (match, _ticks: string, inner: string) =>
      backtickedLatex(inner, mathContext) ?? match,
  );

  const code = maskSpans(result, INLINE_CODE_SPAN_RE, "CODE");
  result = code.masked;

  result = normalizeDoubledDelimiters(result);
  // editor.md examples wrap `\( ... \)` inside `$$ ... $$`; strip the inner
  // pair rather than nesting delimiters.
  result = result.replace(
    /\$\$\s*\\\(([\s\S]*?)\\\)\s*\$\$/g,
    (_match, expr: string) => `\n$$\n${expr.trim()}\n$$\n`,
  );
  result = convertBracketDelimiters(result);
  result = convertParenDelimiters(result);

  const math = maskSpans(result, MATH_SPAN_RE, "MATH");
  result = math.restore(wrapBareLatex(math.masked));
  result = escapeStrayDollars(result);

  return code.restore(result);
}

/**
 * Rewrite a model's maths into delimiters remark-math reads correctly.
 * Idempotent: running it on its own output is a no-op.
 */
export function normalizeMathMarkup(content: string): string {
  if (!content) return content;
  const value = String(content);
  // Decided once for the whole document, not per paragraph: the evidence that
  // a page is about maths is usually in a different paragraph from the
  // undecorated expression that needs the benefit of the doubt.
  const mathContext =
    /\$\$/.test(value) ||
    hasInlineMathCandidate(value) ||
    hasBareLatexTrigger(value);
  return mapMarkdownProse(value, (text) => normalizeProse(text, mathContext));
}

/**
 * Does a `$...$` pair in this text read as a formula? Mirrors the decision
 * `escapeStrayDollars` makes, so renderer routing and rendering agree.
 */
export function hasInlineMathCandidate(content: string): boolean {
  if (!content.includes("$")) return false;
  const withoutEscaped = content.replace(/\\\$/g, "");
  for (const match of withoutEscaped.matchAll(/\$([^$\n]{1,400})\$/g)) {
    const body = match[1];
    const tight = !/^\s/.test(body) && !/\s$/.test(body);
    if (plausibleMathBody(body, tight)) return true;
  }
  return false;
}

/**
 * Does this text contain bare LaTeX `normalizeMathMarkup` would wrap? Used to
 * route between the cheap renderer and the KaTeX one, so it has to agree with
 * the normaliser: under-reporting means the formula never reaches KaTeX, while
 * over-reporting only costs a plugin load.
 */
export function hasBareLatexTrigger(content: string): boolean {
  if (!content.includes("\\")) return false;
  for (const match of content.matchAll(/\\([a-zA-Z]+)/g)) {
    if (isMathTriggerCommand(match[1])) return true;
  }
  return false;
}
