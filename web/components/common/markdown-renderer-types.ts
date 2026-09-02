export interface MarkdownRendererProps {
  content: string;
  className?: string;
  variant?: "default" | "compact" | "prose" | "trace";
  enableMath?: boolean;
  enableCode?: boolean;
  enableMermaid?: boolean;
  enableImages?: boolean;
  allowHtml?: boolean;
  /** Add source-line markers used by synchronized editor previews. */
  trackSourceLines?: boolean;
}
