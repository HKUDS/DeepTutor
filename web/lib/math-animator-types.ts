export type MathAnimatorOutputMode = "video" | "image";

export interface MathAnimatorArtifact {
  type: "video" | "image";
  url: string;
  filename: string;
  content_type?: string;
  label?: string;
}

export interface MathAnimatorResult {
  response: string;
  output_mode: MathAnimatorOutputMode;
  code: {
    language: string;
    content: string;
  };
  artifacts: MathAnimatorArtifact[];
  timings: Record<string, number>;
  render: {
    quality?: string;
    retry_attempts?: number;
    retry_history?: Array<{ attempt: number; error: string }>;
    source_code_path?: string;
    visual_review?: {
      passed?: boolean;
      summary?: string;
      issues?: string[];
      suggested_fix?: string;
      reviewed_frames?: number;
    } | null;
  };
  summary?: {
    summary_text?: string;
    user_request?: string;
    generated_output?: string;
    key_points?: string[];
  };
}

export function extractMathAnimatorResult(
  resultMetadata: Record<string, unknown> | undefined,
): MathAnimatorResult | null {
  if (!resultMetadata) return null;
  const artifacts = Array.isArray(resultMetadata.artifacts)
    ? resultMetadata.artifacts.filter((item): item is MathAnimatorArtifact => {
        return Boolean(
          item &&
          typeof item === "object" &&
          "type" in item &&
          "url" in item &&
          "filename" in item,
        );
      })
    : [];
  const codeRaw =
    resultMetadata.code && typeof resultMetadata.code === "object"
      ? (resultMetadata.code as Record<string, unknown>)
      : {};
  const hasOutputMode =
    resultMetadata.output_mode === "image" ||
    resultMetadata.output_mode === "video";
  const timings =
    resultMetadata.timings && typeof resultMetadata.timings === "object"
      ? (resultMetadata.timings as Record<string, number>)
      : {};
  const render =
    resultMetadata.render && typeof resultMetadata.render === "object"
      ? (resultMetadata.render as MathAnimatorResult["render"])
      : {};
  const outputMode = resultMetadata.output_mode === "image" ? "image" : "video";

  // A plain `response` field is common across capabilities. Only treat the
  // payload as a math-animator result when it carries math-animator-specific
  // artifacts or render metadata.
  if (
    !artifacts.length &&
    !codeRaw.content &&
    !hasOutputMode &&
    Object.keys(timings).length === 0 &&
    Object.keys(render).length === 0
  ) {
    return null;
  }

  return {
    response: String(resultMetadata.response ?? ""),
    output_mode: outputMode,
    code: {
      language: String(codeRaw.language ?? "python"),
      content: String(codeRaw.content ?? ""),
    },
    artifacts,
    timings,
    render,
    summary:
      resultMetadata.summary && typeof resultMetadata.summary === "object"
        ? (resultMetadata.summary as MathAnimatorResult["summary"])
        : undefined,
  };
}
