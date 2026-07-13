"use client";

import dynamic from "next/dynamic";
import SimpleMarkdownRenderer from "./SimpleMarkdownRenderer";

const RichMarkdownRenderer = dynamic(() => import("./RichMarkdownRenderer"), {
  ssr: false,
});

export interface MarkdownRendererProps {
  content: string;
  className?: string;
  variant?: "default" | "compact" | "prose" | "trace";
  enableMath?: boolean;
  enableCode?: boolean;
  enableMermaid?: boolean;
  allowHtml?: boolean;
  /**
   * When true, top-level block elements receive a `data-source-line` attribute
   * pointing at their starting line in the original markdown source. Useful for
   * editor/preview scroll synchronization.
   */
  trackSourceLines?: boolean;
}

// Detection during streaming has a subtle correctness requirement: it must
// be monotonic. Once `true`, it should stay `true` as more tokens arrive so
// the renderer never downgrades from Rich back to Simple (which would cause
// a full subtree remount and a visible flash). The patterns below match
// *opening* tokens — `$$`, `\(`, `\[`, ` ``` ` — rather than requiring a
// matched close. A partial fence still gets the rich treatment, then the
// closer arriving later is just more append-only content with no swap.
function detectMathContent(content: string): boolean {
  if (/(^|[^\\])\$\$/.test(content)) return true;
  if (/\\\(|\\\[/.test(content)) return true;
  // Single-dollar inline math containing LaTeX commands (\cmd) or math operators ({}_^)
  if (
    /(?:^|[^$\\])\$(?!\$|\s)(?:[^$\n]*(?:\\[a-zA-Z]+|[{}_^]))[^$\n]*\$(?!\$)/m.test(
      content,
    )
  )
    return true;
  return false;
}

function detectCodeContent(content: string): boolean {
  // Match any opening triple-backtick, even before the language identifier
  // arrives. Otherwise streaming flips Simple→Rich the moment the language
  // tag lands a few tokens after the fence.
  return /```/.test(content);
}

function detectMermaidContent(content: string): boolean {
  // editor.md style ```flow / ```seq / ```sequence fences are converted to
  // mermaid by processMarkdownContent, so they need to enable the mermaid path
  // as well. Otherwise the converted blocks fall through to the code renderer.
  return /```(?:mermaid|flow|seq|sequence)\b/i.test(content);
}

function detectHtmlContent(content: string): boolean {
  return /<\/?[A-Za-z][\w:-]*(\s|>)/.test(content);
}

export default function MarkdownRenderer({
  content,
  className = "",
  variant = "default",
  enableMath,
  enableCode,
  enableMermaid,
  allowHtml,
  trackSourceLines,
}: MarkdownRendererProps) {
  const resolvedEnableMath = enableMath ?? detectMathContent(content);
  const resolvedEnableCode = enableCode ?? detectCodeContent(content);
  const resolvedEnableMermaid = enableMermaid ?? detectMermaidContent(content);
  const resolvedAllowHtml = allowHtml ?? detectHtmlContent(content);
  // Detection above is intentionally monotonic — once any of the rich
  // triggers fire, more tokens never un-fire them. Combined with the
  // append-only nature of streaming content this gives us a stable
  // Simple→Rich one-way transition (the Rich subtree mounts once and
  // stays). No additional lock state is needed.
  const shouldUseRich =
    variant !== "trace" &&
    (trackSourceLines ||
      resolvedEnableMath ||
      resolvedEnableCode ||
      resolvedEnableMermaid ||
      resolvedAllowHtml);

  if (!shouldUseRich) {
    return (
      <SimpleMarkdownRenderer
        content={content}
        className={className}
        variant={variant}
      />
    );
  }

  return (
    <RichMarkdownRenderer
      content={content}
      className={className}
      variant={variant}
      enableMath={resolvedEnableMath}
      enableCode={resolvedEnableCode}
      enableMermaid={resolvedEnableMermaid}
      allowHtml={resolvedAllowHtml}
      trackSourceLines={trackSourceLines}
    />
  );
}
