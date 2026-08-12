"use client";

import VisualizationViewer from "@/components/visualize/VisualizationViewer";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { useTranslation } from "react-i18next";
import type { Block } from "@/lib/book-types";
import type {
  VisualizeResult,
  VisualizeTextRenderType,
} from "@/lib/visualize-types";

export interface FigureBlockProps {
  block: Block;
}

const FIGURE_RENDER_TYPES: ReadonlySet<VisualizeTextRenderType> = new Set([
  "svg",
  "chartjs",
  "mermaid",
]);

function coerceRenderType(
  value: unknown,
  language: string,
): VisualizeTextRenderType {
  if (
    typeof value === "string" &&
    (FIGURE_RENDER_TYPES as Set<string>).has(value)
  ) {
    return value as VisualizeTextRenderType;
  }
  if (language === "javascript" || language === "js") return "chartjs";
  if (language === "mermaid") return "mermaid";
  return "svg";
}

export default function FigureBlock({ block }: FigureBlockProps) {
  const { t } = useTranslation();
  const code =
    (block.payload?.code as
      | { language?: string; content?: string }
      | undefined) || {};
  const language = String(code.language || "svg");
  const content = String(code.content || "");
  const description = block.payload?.description
    ? String(block.payload.description)
    : "";
  const chartType = block.payload?.chart_type
    ? String(block.payload.chart_type)
    : "";

  if (!content.trim()) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 p-4 text-xs italic text-[var(--muted-foreground)]">
        {t("(Figure payload is empty)")}
      </div>
    );
  }

  const renderType = coerceRenderType(block.payload?.render_type, language);

  const result: VisualizeResult = {
    response: description,
    render_type: renderType,
    code: { language, content },
    analysis: {
      render_type: renderType,
      description,
      data_description: "",
      chart_type: chartType,
      visual_elements: [],
      rationale: "",
    },
    review: {
      optimized_code: "",
      changed: false,
      review_notes: "",
    },
  };

  return (
    <figure className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-3 shadow-sm">
      <VisualizationViewer result={result} />
      {description && (
        <figcaption className="mt-3 text-xs leading-snug text-[var(--muted-foreground)]">
          <MarkdownRenderer content={description} variant="default" />
        </figcaption>
      )}
    </figure>
  );
}
