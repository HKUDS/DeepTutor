export type VisualizeRenderType = "svg" | "chartjs" | "mermaid";
export type VisualizeRenderMode = "auto" | "svg" | "chartjs" | "mermaid";

export interface VisualizeFormConfig {
  render_mode: VisualizeRenderMode;
}

export const DEFAULT_VISUALIZE_CONFIG: VisualizeFormConfig = {
  render_mode: "auto",
};

export function buildVisualizeWSConfig(
  cfg: VisualizeFormConfig,
): Record<string, unknown> {
  return { render_mode: cfg.render_mode };
}

export interface VisualizeResult {
  response: string;
  render_type: VisualizeRenderType;
  code: {
    language: string;
    content: string;
  };
  analysis: {
    render_type: string;
    description: string;
    data_description: string;
    chart_type: string;
    visual_elements: string[];
    rationale: string;
  };
  review: {
    optimized_code: string;
    changed: boolean;
    review_notes: string;
  };
}

export function extractVisualizeResult(
  resultMetadata: Record<string, unknown> | undefined,
): VisualizeResult | null {
  if (!resultMetadata) return null;

  const renderType = resultMetadata.render_type;
  if (renderType !== "svg" && renderType !== "chartjs" && renderType !== "mermaid") return null;

  const codeRaw =
    resultMetadata.code && typeof resultMetadata.code === "object"
      ? (resultMetadata.code as Record<string, unknown>)
      : {};

  if (!codeRaw.content) return null;

  return {
    response: String(resultMetadata.response ?? ""),
    render_type: renderType,
    code: {
      language: String(codeRaw.language ?? ""),
      content: String(codeRaw.content ?? ""),
    },
    analysis:
      resultMetadata.analysis && typeof resultMetadata.analysis === "object"
        ? (resultMetadata.analysis as VisualizeResult["analysis"])
        : {
            render_type: renderType,
            description: "",
            data_description: "",
            chart_type: "",
            visual_elements: [],
            rationale: "",
          },
    review:
      resultMetadata.review && typeof resultMetadata.review === "object"
        ? (resultMetadata.review as VisualizeResult["review"])
        : { optimized_code: "", changed: false, review_notes: "" },
  };
}
