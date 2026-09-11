import type { MathAnimatorResult } from "@/lib/math-animator-types";
import { extractMathAnimatorResult } from "@/lib/math-animator-types";

export type VisualizeTextRenderType = "svg" | "chartjs" | "mermaid" | "html";
export type VisualizeManimRenderType = "manim_video" | "manim_image";
export type VisualizeRenderType = string;
export type VisualizeRenderMode = "auto" | (string & {});

export interface VisualizeFormConfig {
  render_mode: VisualizeRenderMode;
  quality: "low" | "medium" | "high";
  style_hint: string;
}

export const DEFAULT_VISUALIZE_CONFIG: VisualizeFormConfig = {
  render_mode: "auto",
  quality: "medium",
  style_hint: "",
};

export function buildVisualizeWSConfig(
  cfg: VisualizeFormConfig,
): Record<string, unknown> {
  return {
    render_mode: cfg.render_mode,
    quality: cfg.quality,
    style_hint: cfg.style_hint.trim(),
  };
}

const VISUALIZE_RENDER_LABELS: Record<string, string> = {
  auto: "Auto",
  chartjs: "Chart.js",
  svg: "SVG",
  mermaid: "Mermaid",
  html: "HTML",
  geogebra: "GeoGebra",
  manim_video: "Animation",
  manim_image: "Storyboard",
};

export function isManimRenderType(
  renderType: string,
): renderType is VisualizeManimRenderType {
  return renderType === "manim_video" || renderType === "manim_image";
}

export function summarizeVisualizeConfig(
  cfg: VisualizeFormConfig,
  translate?: (key: string) => string,
): string {
  const label = VISUALIZE_RENDER_LABELS[cfg.render_mode] ?? cfg.render_mode;
  const text = translate ? translate(label) : label;
  if (isManimRenderType(cfg.render_mode)) {
    const qLabel = cfg.quality.charAt(0).toUpperCase() + cfg.quality.slice(1);
    const q = translate ? translate(qLabel) : qLabel;
    return `${text} · ${q}`;
  }
  return text;
}

export interface VisualizerRendererRef {
  id: string;
  version: string;
  target: "native" | "iframe" | "artifact";
  native_renderer: string;
  entry_url: string;
}

export interface VisualizationPayload {
  format: string;
  data: unknown;
}

export interface VisualizationPresentation {
  title: string;
  description: string;
  alt_text: string;
  aspect_ratio: string;
}

export interface VisualizeCanvasResult {
  schema_version: string;
  response: string;
  render_type: string;
  renderer: VisualizerRendererRef;
  payload: VisualizationPayload;
  presentation: VisualizationPresentation;
  interaction: { events: string[] };
  fallback: Record<string, unknown>;
  code: { language: string; content: string };
  analysis: {
    render_type: string;
    description: string;
    data_description: string;
    chart_type: string;
    visual_elements: string[];
    rationale: string;
    engine?: string;
    requested_type?: string;
  };
  review: {
    optimized_code: string;
    changed: boolean;
    review_notes: string;
  };
}

export interface VisualizeManimResult {
  render_type: VisualizeManimRenderType;
  manim: MathAnimatorResult;
}

export type VisualizeResult = VisualizeCanvasResult | VisualizeManimResult;

export function isManimResult(
  result: VisualizeResult,
): result is VisualizeManimResult {
  return isManimRenderType(result.render_type) && "manim" in result;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function serializePayload(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? "");
  }
}

export function extractVisualizeResult(
  resultMetadata: Record<string, unknown> | undefined,
): VisualizeResult | null {
  if (!resultMetadata) return null;
  const renderType = String(resultMetadata.render_type ?? "").trim();
  if (!renderType) return null;

  if (isManimRenderType(renderType)) {
    const manim = extractMathAnimatorResult(resultMetadata);
    if (!manim) return null;
    return { render_type: renderType, manim };
  }

  const rendererRaw = record(resultMetadata.renderer);
  const payloadRaw = record(resultMetadata.payload);
  const codeRaw = record(resultMetadata.code);
  const analysisRaw = record(resultMetadata.analysis);
  const reviewRaw = record(resultMetadata.review);
  const presentationRaw = record(resultMetadata.presentation);
  const interactionRaw = record(resultMetadata.interaction);

  // v1 envelope is canonical. `code` remains a compatibility source for old
  // saved sessions and Book blocks created before the canvas protocol.
  const payloadData = Object.prototype.hasOwnProperty.call(payloadRaw, "data")
    ? payloadRaw.data
    : codeRaw.content;
  const content = serializePayload(payloadData);
  if (!content.trim()) return null;

  const inferredRenderer =
    renderType === "svg" ||
    renderType === "mermaid" ||
    renderType === "chartjs" ||
    renderType === "html" ||
    renderType === "geogebra"
      ? renderType
      : "";

  return {
    schema_version: String(
      resultMetadata.schema_version ?? "deeptutor.visualization/legacy",
    ),
    response: String(resultMetadata.response ?? ""),
    render_type: renderType,
    renderer: {
      id: String(rendererRaw.id ?? renderType),
      version: String(rendererRaw.version ?? "1.0.0"),
      target: (rendererRaw.target === "iframe"
        ? "iframe"
        : rendererRaw.target === "artifact"
          ? "artifact"
          : "native") as VisualizerRendererRef["target"],
      native_renderer: String(rendererRaw.native_renderer ?? inferredRenderer),
      entry_url: String(rendererRaw.entry_url ?? ""),
    },
    payload: {
      format: String(payloadRaw.format ?? codeRaw.language ?? "text/plain"),
      data: payloadData,
    },
    presentation: {
      title: String(presentationRaw.title ?? ""),
      description: String(
        presentationRaw.description ?? analysisRaw.description ?? "",
      ),
      alt_text: String(presentationRaw.alt_text ?? ""),
      aspect_ratio: String(presentationRaw.aspect_ratio ?? ""),
    },
    interaction: {
      events: Array.isArray(interactionRaw.events)
        ? interactionRaw.events.map(String)
        : [],
    },
    fallback: record(resultMetadata.fallback),
    code: {
      language: String(codeRaw.language ?? "text"),
      content,
    },
    analysis: {
      render_type: String(analysisRaw.render_type ?? renderType),
      description: String(analysisRaw.description ?? ""),
      data_description: String(analysisRaw.data_description ?? ""),
      chart_type: String(analysisRaw.chart_type ?? ""),
      visual_elements: Array.isArray(analysisRaw.visual_elements)
        ? analysisRaw.visual_elements.map(String)
        : [],
      rationale: String(analysisRaw.rationale ?? ""),
      engine: analysisRaw.engine ? String(analysisRaw.engine) : undefined,
      requested_type: analysisRaw.requested_type
        ? String(analysisRaw.requested_type)
        : undefined,
    },
    review: {
      optimized_code: String(reviewRaw.optimized_code ?? ""),
      changed: Boolean(reviewRaw.changed),
      review_notes: String(reviewRaw.review_notes ?? ""),
    },
  };
}
