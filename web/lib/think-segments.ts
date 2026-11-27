/**
 * Splits a raw assistant response into ordinary markdown segments and
 * "model thinking" segments produced by reasoning models that emit their
 * scratchpad as <think> ... </think> (or <thinking> ... </thinking>) blocks
 * directly inside the response stream.
 *
 * This only deals with thinking that lives **outside** the system trace
 * (i.e. content the orchestrator forwards as the assistant's user-facing
 * answer). Trace panels render their own <think>-shaped chunks separately
 * and are not touched here.
 *
 * The parser is robust to two on-the-wire shapes:
 *
 *   1. Raw form, as the model streams it:
 *        "<think>foo</think>bar"
 *
 *   2. Post-normalized form produced by `normalizeMarkdownForDisplay`,
 *      which wraps unknown lowercase tags in inline-code backticks so
 *      React stops complaining about unknown elements:
 *        "`<think>`foo`</think>`bar"
 *
 * It also tolerates open-without-close (still streaming the scratchpad)
 * and skips any tags that live inside fenced code blocks.
 */

export interface TextSegment {
  kind: "text";
  content: string;
}

export interface ThinkSegment {
  kind: "think";
  content: string;
  /** False while the model is still streaming inside the open tag. */
  closed: boolean;
}

export type ContentSegment = TextSegment | ThinkSegment;

const FENCE_LINE_REGEX = /^ {0,3}(`{3,}|~{3,})([^\r\n]*)(?:\r?\n|$)/gm;
const FENCED_PLACEHOLDER_REGEX = /\u0000FENCED_(\d+)\u0000/g;

// `?<\s*think(?:ing)?\b[^>]*>`?
//   leading/trailing backtick is optional so we match both the raw streaming
//   form and the post-`escapeUnknownHtmlTags` form. The `[^>]*` swallows any
//   stray attributes some providers emit (e.g. `<thinking duration="3s">`).
const OPEN_TAG_REGEX = /`?<\s*(think(?:ing)?)\b[^>]*>`?/i;

function closeTagRegex(tag: string): RegExp {
  return new RegExp(`\`?<\\s*/\\s*${tag}\\s*>\`?`, "i");
}

function maskFencedCode(input: string): { masked: string; blocks: string[] } {
  const blocks: string[] = [];
  let masked = "";
  let cursor = 0;
  let start = -1;
  let opening = "";
  const appendBlock = (end: number) => {
    masked += input.slice(cursor, start);
    blocks.push(input.slice(start, end));
    masked += `\u0000FENCED_${blocks.length - 1}\u0000`;
    cursor = end;
    start = -1;
    opening = "";
  };

  for (const match of input.matchAll(FENCE_LINE_REGEX)) {
    const marker = match[1];
    if (start >= 0) {
      if (
        marker[0] === opening[0] &&
        marker.length >= opening.length &&
        match[2].trim() === ""
      ) {
        appendBlock(match.index + match[0].length);
      }
    } else if (marker[0] !== "`" || !match[2].includes("`")) {
      start = match.index;
      opening = marker;
    }
  }
  // A streaming code block remains code until its matching fence arrives.
  if (start >= 0) appendBlock(input.length);
  masked += input.slice(cursor);
  return { masked, blocks };
}

function restoreFencedCode(input: string, blocks: string[]): string {
  if (blocks.length === 0) return input;
  return input.replace(FENCED_PLACEHOLDER_REGEX, (_, idx: string) => {
    const i = Number(idx);
    return Number.isFinite(i) ? (blocks[i] ?? "") : "";
  });
}

/**
 * Strip the leading newlines that typically follow `<think>` and the
 * trailing newlines that precede `</think>`, so the collapsible card
 * does not render a top/bottom gap.
 */
function trimThinkContent(content: string): string {
  return content.replace(/^\s+/, "").replace(/\s+$/, "");
}

export function parseModelThinkingSegments(input: string): ContentSegment[] {
  if (!input) return [];
  if (!/<\s*think(?:ing)?\b/i.test(input)) {
    return [{ kind: "text", content: input }];
  }

  const { masked, blocks } = maskFencedCode(input);
  const segments: ContentSegment[] = [];
  let cursor = 0;

  while (cursor < masked.length) {
    const tail = masked.slice(cursor);
    const open = OPEN_TAG_REGEX.exec(tail);
    if (!open) {
      const text = restoreFencedCode(tail, blocks);
      if (text.length > 0) segments.push({ kind: "text", content: text });
      break;
    }

    if (open.index > 0) {
      const prefix = restoreFencedCode(tail.slice(0, open.index), blocks);
      if (prefix.length > 0) segments.push({ kind: "text", content: prefix });
    }

    const tag = open[1].toLowerCase();
    const afterOpen = tail.slice(open.index + open[0].length);
    const close = closeTagRegex(tag).exec(afterOpen);

    if (!close) {
      const body = restoreFencedCode(afterOpen, blocks);
      segments.push({
        kind: "think",
        content: trimThinkContent(body),
        closed: false,
      });
      break;
    }

    const body = restoreFencedCode(afterOpen.slice(0, close.index), blocks);
    segments.push({
      kind: "think",
      content: trimThinkContent(body),
      closed: true,
    });
    cursor += open.index + open[0].length + close.index + close[0].length;
  }

  return segments;
}

/** True when `input` contains at least one model-thinking block. */
export function hasModelThinking(input: string): boolean {
  if (!input) return false;
  return /<\s*think(?:ing)?\b/i.test(input);
}
