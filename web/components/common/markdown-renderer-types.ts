export interface MarkdownRendererProps {
  content: string;
  /** Opt-in learning content boundary, with its existing unscaled pixel size. */
  learningTextSize?: number;
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
