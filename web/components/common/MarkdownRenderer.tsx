"use client";

import dynamic from "next/dynamic";
import { hasMarkdownMath } from "@/lib/latex";
import SimpleMarkdownRenderer from "./SimpleMarkdownRenderer";
import type { MarkdownRendererProps } from "./markdown-renderer-types";

export type { MarkdownRendererProps } from "./markdown-renderer-types";

const RichMarkdownRenderer = dynamic(() => import("./RichMarkdownRenderer"), {
  ssr: false,
});

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
  enableImages,
  allowHtml,
  trackSourceLines,
}: MarkdownRendererProps) {
  const resolvedEnableMath = enableMath ?? hasMarkdownMath(content);
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
      enableImages={enableImages}
      allowHtml={resolvedAllowHtml}
      trackSourceLines={trackSourceLines}
    />
  );
}
