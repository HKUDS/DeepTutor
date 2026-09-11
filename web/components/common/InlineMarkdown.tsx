"use client";

import dynamic from "next/dynamic";
import { hasMarkdownMath } from "@/lib/latex";
import { decodeEscapedUnicodeForDisplay } from "@/lib/markdown-display";

const RichInlineMarkdown = dynamic(() => import("./RichInlineMarkdown"), {
  ssr: false,
});

// Emphasis, inline code and links are the rest of what a tutor writes into a
// question stem or an option. Matching them here (not just math) is what keeps
// `**听懂**` from reaching the learner with its asterisks attached.
const INLINE_MARKUP_RE = /(\*\*|__|`|~~|\[[^\]]+\]\()/;

/**
 * A short string a model wrote, rendered as the inline markdown it is.
 *
 * Question stems, answer options and grade explanations were printed as plain
 * text, so a physics or maths question showed the learner raw `$V^\pi$` and a
 * bolded cue showed its asterisks. They are also *short* and sit inside
 * buttons and one-line rows, so they cannot use the block renderer: this one
 * emits phrasing content only, and loads KaTeX at all only when the string
 * actually contains something to render.
 */
export default function InlineMarkdown({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  const text = decodeEscapedUnicodeForDisplay(content ?? "");
  const rich = hasMarkdownMath(text) || INLINE_MARKUP_RE.test(text);

  if (!rich) {
    return className ? <span className={className}>{text}</span> : <>{text}</>;
  }

  const rendered = <RichInlineMarkdown content={text} />;
  return className ? <span className={className}>{rendered}</span> : rendered;
}
