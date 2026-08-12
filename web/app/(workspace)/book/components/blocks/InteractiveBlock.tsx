"use client";

import VisualizationViewer from "@/components/visualize/VisualizationViewer";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { useTranslation } from "react-i18next";
import type { Block } from "@/lib/book-types";
import type { VisualizeResult } from "@/lib/visualize-types";

export interface InteractiveBlockProps {
  block: Block;
}

export default function InteractiveBlock({ block }: InteractiveBlockProps) {
  const { t } = useTranslation();
  const code =
    (block.payload?.code as
      | { language?: string; content?: string }
      | undefined) || {};
  const content = String(code.content || "");
  const description = block.payload?.description
    ? String(block.payload.description)
    : "";
  const chartType = block.payload?.chart_type
    ? String(block.payload.chart_type)
    : "interactive";

  if (!content.trim()) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 p-4 text-xs italic text-[var(--muted-foreground)]">
        {t("(Interactive payload is empty)")}
      </div>
    );
  }

  const result: VisualizeResult = {
    response: description,
    render_type: "html",
    code: { language: "html", content },
    analysis: {
      render_type: "html",
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
