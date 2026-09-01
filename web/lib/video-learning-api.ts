import { apiFetch, apiUrl } from "@/lib/api";

export type VideoProvider = "youtube" | "invidious";

export interface TranscriptCue {
  start: number;
  end: number;
  text: string;
}

export interface TimedSegment extends TranscriptCue {
  locator: number;
}

export type VideoPlayback =
  | {
      provider: "youtube";
      kind: "youtube_iframe";
      video_id: string;
      start_seconds: number;
    }
  | {
      provider: "invidious";
      kind: "html5";
      format_id: string;
      mime_type: string;
      stream_url: string;
      subtitles_url: string;
      start_seconds: number;
    };

export interface TimedMediaMaterial {
  version: number;
  type: "timed_media";
  material_id: string;
  source: {
    provider: "youtube";
    video_id: string;
    url: string;
    entry_time_seconds: number;
  };
  metadata: {
    title: string;
    author: string;
    duration_seconds: number;
    thumbnail_url?: string;
  };
  transcript: {
    status: "ready" | "unavailable";
    reason: string;
    language: string;
    source: string;
    cues: TranscriptCue[];
  };
  segments: TimedSegment[];
  learning: { last_position: number };
  playback: VideoPlayback;
}

export interface VideoLearningSettings {
  version: 1;
  default_provider: VideoProvider;
  youtube: { transcript_provider: "youtube_transcript_api" | "none" };
  invidious: { api_base_url: string; public_base_url: string };
}

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(
      String(payload?.detail || `Request failed (${response.status})`),
    );
  }
  return (await response.json()) as T;
}

export async function resolveVideo(
  url: string,
  language = "",
  providerOverride?: VideoProvider,
): Promise<TimedMediaMaterial> {
  return unwrap(
    await apiFetch(apiUrl("/api/v1/video-learning/materials/resolve"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        language,
        ...(providerOverride ? { provider_override: providerOverride } : {}),
      }),
    }),
  );
}

export async function getVideoMaterial(
  materialId: string,
): Promise<TimedMediaMaterial> {
  return unwrap(
    await apiFetch(
      apiUrl(
        `/api/v1/video-learning/materials/${encodeURIComponent(materialId)}`,
      ),
      {
        cache: "no-store",
      },
    ),
  );
}

export async function saveVideoProgress(
  materialId: string,
  timeSeconds: number,
  durationSeconds: number,
): Promise<void> {
  await unwrap(
    await apiFetch(
      apiUrl(
        `/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/progress`,
      ),
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          time_seconds: Math.max(0, timeSeconds),
          duration_seconds: Math.max(0, durationSeconds),
        }),
      },
    ),
  );
}

export async function getVideoLearningSettings(): Promise<VideoLearningSettings> {
  return unwrap(
    await apiFetch(apiUrl("/api/v1/settings/video-learning"), {
      cache: "no-store",
    }),
  );
}

export async function saveVideoLearningSettings(
  settings: VideoLearningSettings,
): Promise<VideoLearningSettings> {
  return unwrap(
    await apiFetch(apiUrl("/api/v1/settings/video-learning"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }),
  );
}

export async function testInvidious(
  settings: VideoLearningSettings,
): Promise<{ ok: boolean; message: string }> {
  return unwrap(
    await apiFetch(apiUrl("/api/v1/settings/video-learning/test-invidious"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }),
  );
}
