"use client";

/**
 * A small, purpose-built Markdown renderer for the reader's text view.
 *
 * It is not a general Markdown engine: it renders exactly the constructs
 * extracted web/EPUB content actually produces (bold, italic, inline code,
 * links, blockquotes, bullet lists, horizontal rules) and nothing that would
 * require a multi-line block model (tables, nested lists).
 *
 * The one rule every branch below must hold: the DOM `textContent` of what it
 * renders, read start to end, must equal the original source line exactly.
 * Recogito's TextPosition selectors and the server's verbatim-quote check
 * both resolve against that text, so a highlighted "**bold**" that visually
 * shows only "bold" still has to leave the two `**` where a selection can
 * still see them — just visually collapsed to nothing. `HiddenMark` is that
 * collapse: present in the DOM, `aria-hidden`, zero-size, so `Range.toString()`
 * still walks through it but nothing is painted.
 */

import { Fragment, type ReactNode } from "react";

function HiddenMark({ text }: { text: string }) {
  if (!text) return null;
  return (
    <span
      aria-hidden="true"
      className="inline-block size-0 overflow-hidden align-top text-[0px]"
    >
      {text}
    </span>
  );
}

// Alternatives are tried in order at each position, so `**bold**` is claimed
// by the first branch before the single-`*` italic branch ever sees it.
const INLINE_PATTERN =
  /(\*\*|__)([^\n]+?)\1|`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)|(\*|_)([^\s*_][^\n]*?)\6(?!\w)/g;

/** Bold, italic, inline code, and links within one line of plain text. */
export function InlineMarkdown({ text }: { text: string }): ReactNode {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  // `matchAll` never mutates the shared pattern's `lastIndex` — it is
  // specified to operate on an internal copy — so this stays safe to call
  // with a module-level regex from a component body.
  for (const match of text.matchAll(INLINE_PATTERN)) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const [
      whole,
      boldDelim,
      boldContent,
      codeContent,
      linkLabel,
      linkUrl,
      italicDelim,
      italicContent,
    ] = match;
    if (boldDelim) {
      nodes.push(
        <Fragment key={key++}>
          <HiddenMark text={boldDelim} />
          <strong>{boldContent}</strong>
          <HiddenMark text={boldDelim} />
        </Fragment>,
      );
    } else if (codeContent !== undefined) {
      nodes.push(
        <Fragment key={key++}>
          <HiddenMark text="`" />
          <code className="rounded bg-[var(--muted)] px-1 py-0.5 font-mono text-[0.92em]">
            {codeContent}
          </code>
          <HiddenMark text="`" />
        </Fragment>,
      );
    } else if (linkLabel !== undefined) {
      nodes.push(
        <Fragment key={key++}>
          <HiddenMark text="[" />
          <a
            href={linkUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--primary)] underline decoration-[color-mix(in_srgb,var(--primary)_35%,transparent)] underline-offset-2 hover:decoration-[var(--primary)]"
          >
            {linkLabel}
          </a>
          <HiddenMark text={`](${linkUrl})`} />
        </Fragment>,
      );
    } else if (italicDelim) {
      nodes.push(
        <Fragment key={key++}>
          <HiddenMark text={italicDelim} />
          <em>{italicContent}</em>
          <HiddenMark text={italicDelim} />
        </Fragment>,
      );
    }
    lastIndex = (match.index ?? lastIndex) + whole.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return <>{nodes}</>;
}

const RULE_PATTERN = /^\s{0,3}(?:(-\s*){3,}|(\*\s*){3,}|(_\s*){3,})$/;
const BLOCKQUOTE_PATTERN = /^(\s{0,3}>\s?)([\s\S]*)$/;
const BULLET_PATTERN = /^(\s{0,3}[-*+]\s+)(\S[\s\S]*)$/;

/**
 * One rendered line of body text: block-level markers first (a line is at
 * most one of rule / blockquote / bullet), then inline formatting on
 * whatever text remains.
 */
export function MarkdownLine({ text }: { text: string }): ReactNode {
  if (RULE_PATTERN.test(text) && text.trim().length >= 3) {
    return (
      <>
        <HiddenMark text={text} />
        <hr className="my-4 border-[var(--border)]" />
      </>
    );
  }

  const blockquote = BLOCKQUOTE_PATTERN.exec(text);
  if (blockquote) {
    const [, marker, rest] = blockquote;
    return (
      <span className="block border-l-2 border-[var(--border)] pl-3 text-[var(--muted-foreground)]">
        <HiddenMark text={marker} />
        <InlineMarkdown text={rest} />
      </span>
    );
  }

  const bullet = BULLET_PATTERN.exec(text);
  if (bullet) {
    const [, marker, rest] = bullet;
    return (
      <span className="relative block pl-4 before:absolute before:left-0 before:content-['•'] before:text-[var(--muted-foreground)]">
        <HiddenMark text={marker} />
        <InlineMarkdown text={rest} />
      </span>
    );
  }

  return <InlineMarkdown text={text} />;
}
