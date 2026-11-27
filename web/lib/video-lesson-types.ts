export interface VideoLessonArtifact {
  type: "html";
  url: string;
  filename: string;
  content_type?: string;
  label?: string;
}

export interface VideoLessonResult {
  response: string;
  title: string;
  page: VideoLessonArtifact;
  code: string;
  durationSeconds: number | null;
  attempts: number;
}

/** The lesson page and its metadata from a ``video_lesson`` result event, or null. */
export function extractVideoLessonResult(
  resultMetadata: Record<string, unknown> | undefined,
): VideoLessonResult | null {
  if (!resultMetadata) return null;
  const artifacts = Array.isArray(resultMetadata.artifacts)
    ? resultMetadata.artifacts
    : [];
  const page = artifacts.find(
    (item): item is VideoLessonArtifact =>
      Boolean(item) &&
      typeof item === "object" &&
      (item as Record<string, unknown>).type === "html" &&
      typeof (item as Record<string, unknown>).url === "string" &&
      Boolean(((item as Record<string, unknown>).url as string).trim()),
  );
  if (!page) return null;
  const code =
    resultMetadata.code && typeof resultMetadata.code === "object"
      ? String((resultMetadata.code as Record<string, unknown>).content ?? "")
      : "";
  const render =
    resultMetadata.render && typeof resultMetadata.render === "object"
      ? (resultMetadata.render as Record<string, unknown>)
      : {};
  const duration = Number(render.duration_seconds);
  return {
    response: String(resultMetadata.response ?? ""),
    title: String(resultMetadata.title ?? page.label ?? ""),
    page,
    code,
    durationSeconds: Number.isFinite(duration) && duration > 0 ? duration : null,
    attempts: Array.isArray(render.attempts) ? render.attempts.length : 0,
  };
}
