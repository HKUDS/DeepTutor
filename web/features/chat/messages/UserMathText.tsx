"use client";

import { useMemo, type CSSProperties } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";

type UserMathSegment =
  | { kind: "text"; value: string }
  | { kind: "math"; value: string; display: boolean };

const FENCED_CODE_RE = /(```[\s\S]*?```|~~~[\s\S]*?~~~)/g;
const INLINE_CODE_RE = /(`[^`\n]*`)/g;

/**
 * Split a learner's message into literal text and explicit math.
 *
 * Only `$...$` and `$$...$$` count: the learner opted in, so their delimiters
 * are the intent. Fenced code and inline code stay literal, and a pair that
 * does not read as a formula (prices, paths, `$PATH`) stays literal too.
 */
export function splitUserMath(content: string): UserMathSegment[] {
  const segments: UserMathSegment[] = [];
  for (const chunk of content.split(FENCED_CODE_RE)) {
    if (!chunk) continue;
    if (/^(```|~~~)/.test(chunk)) {
      appendText(segments, chunk);
      continue;
    }
    for (const part of chunk.split(INLINE_CODE_RE)) {
      if (!part) continue;
      if (/^`[^`\n]*`$/.test(part)) {
        appendText(segments, part);
        continue;
      }
      splitProse(part, segments);
    }
  }
  return segments;
}

function splitProse(text: string, segments: UserMathSegment[]): void {
  let cursor = 0;
  while (cursor < text.length) {
    const open = findDollar(text, cursor);
    if (open === -1) {
      appendText(segments, text.slice(cursor));
      return;
    }
    const display = text[open + 1] === "$";
    const bodyStart = open + (display ? 2 : 1);
    const close = display
      ? findDoubleDollar(text, bodyStart)
      : findDollar(text, bodyStart);
    if (close === -1) {
      appendText(segments, text.slice(cursor));
      return;
    }
    const body = text.slice(bodyStart, close);
    const isMath = display
      ? body.trim().length > 0
      : looksLikeInlineMath(body);
    if (isMath) {
      appendText(segments, text.slice(cursor, open));
      segments.push({ kind: "math", value: body, display });
      cursor = close + (display ? 2 : 1);
    } else {
      // Keep the opening delimiter literal and keep looking after it.
      appendText(segments, text.slice(cursor, bodyStart));
      cursor = bodyStart;
    }
  }
}

function findDollar(text: string, from: number): number {
  let index = text.indexOf("$", from);
  while (index !== -1) {
    if (!isEscaped(text, index)) return index;
    index = text.indexOf("$", index + 1);
  }
  return -1;
}

function findDoubleDollar(text: string, from: number): number {
  let index = text.indexOf("$$", from);
  while (index !== -1) {
    if (!isEscaped(text, index)) return index;
    index = text.indexOf("$$", index + 2);
  }
  return -1;
}

function isEscaped(text: string, index: number): boolean {
  return text[index - 1] === "\\";
}

/**
 * An explicit `$...$` pair that reads as math rather than prose or money.
 *
 * `$5 和 $10` and `$5 and $10` do not read as formulas, `$PATH` has no
 * operator, while `$x$`, `$x=1$`, `$f(x)$` and `$\alpha$` pass.
 */
function looksLikeInlineMath(body: string): boolean {
  const value = body.trim();
  if (!value || value.length > 400 || body.includes("\n")) return false;
  // A price range like `$5-$10` pairs its dollars with a trailing operator.
  if (/[+\-*/]$/.test(value)) return false;
  if (/[\\^_=+\-*/<>()]/.test(value)) return true;
  if (/^\d+(\.\d+)?$/.test(value)) return true;
  return /^[A-Za-z]$/.test(value);
}

function appendText(segments: UserMathSegment[], value: string): void {
  if (!value) return;
  const previous = segments[segments.length - 1];
  if (previous?.kind === "text") {
    previous.value += value;
    return;
  }
  segments.push({ kind: "text", value });
}

function MathSegment({
  segment,
}: {
  segment: Extract<UserMathSegment, { kind: "math" }>;
}) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(segment.value, {
        displayMode: segment.display,
        throwOnError: true,
        trust: false,
        strict: "ignore",
        maxExpand: 1000,
        maxSize: 20,
        output: "htmlAndMathml",
      });
    } catch {
      return null;
    }
  }, [segment.value, segment.display]);

  if (!html) {
    return (
      <span className="whitespace-pre-wrap">
        {segment.display ? `$$${segment.value}$$` : `$${segment.value}$`}
      </span>
    );
  }

  return segment.display ? (
    <div
      dir="ltr"
      className="my-2 overflow-x-auto whitespace-normal"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  ) : (
    <span
      dir="ltr"
      className="mx-0.5 inline-block whitespace-normal align-middle"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

/** A user message with only its explicit formulas rendered. */
export default function UserMathText({
  content,
  size = 14,
}: {
  content: string;
  size?: number;
}) {
  const source = typeof content === "string" ? content : "";
  const segments = useMemo(() => splitUserMath(source), [source]);

  return (
    <div
      className="learning-text"
      style={{ "--learning-text-base": `${size}px` } as CSSProperties}
    >
      {segments.map((segment, index) =>
        segment.kind === "text" ? (
          <span key={index} className="whitespace-pre-wrap">
            {segment.value}
          </span>
        ) : (
          <MathSegment key={index} segment={segment} />
        ),
      )}
    </div>
  );
}
