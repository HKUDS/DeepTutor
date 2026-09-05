import { apiFetch, apiUrl } from "@/lib/api";

export type VideoProvider = "youtube" | "invidious";

export interface TranscriptCue {
  words?: { start: number; end: number; text: string }[];
  lines?: string[];
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

export interface VideoNote {
  notebook_id: string;
  note_id: string;
  material_id: string;
  body: string;
  time_seconds: number;
  locator: number;
  quote: string;
  created_at: number;
  updated_at: number;
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
    const detail = (payload as { detail?: unknown })?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof (detail as { message?: unknown } | undefined)?.message ===
            "string"
          ? (detail as { message: string }).message
          : null;
    throw new Error(message || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function listVideoNotes(materialId: string): Promise<VideoNote[]> {
  return unwrap(
    await apiFetch(
      apiUrl(
        `/api/video-learning/materials/${encodeURIComponent(materialId)}/notes`,
      ),
      { cache: "no-store" },
    ),
  );
}

export async function createVideoNote(
  materialId: string,
  body: string,
  timeSeconds: number,
): Promise<VideoNote> {
  return unwrap(
    await apiFetch(
      apiUrl(
        `/api/video-learning/materials/${encodeURIComponent(materialId)}/notes`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body, time_seconds: timeSeconds }),
      },
    ),
  );
}

export async function updateVideoNote(
  materialId: string,
  noteId: string,
  body: string,
): Promise<VideoNote> {
  return unwrap(
    await apiFetch(
      apiUrl(
        `/api/video-learning/materials/${encodeURIComponent(materialId)}/notes/${encodeURIComponent(noteId)}`,
      ),
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      },
    ),
  );
}

export async function deleteVideoNote(
  materialId: string,
  noteId: string,
): Promise<void> {
  await unwrap(
    await apiFetch(
      apiUrl(
        `/api/video-learning/materials/${encodeURIComponent(materialId)}/notes/${encodeURIComponent(noteId)}`,
      ),
      { method: "DELETE" },
    ),
  );
}

export async function resolveVideo(
  url: string,
  language = "",
  providerOverride?: VideoProvider,
): Promise<TimedMediaMaterial> {
  return unwrap(
    await apiFetch(apiUrl("/api/video-learning/materials/resolve"), {
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
      apiUrl(`/api/video-learning/materials/${encodeURIComponent(materialId)}`),
      {
        cache: "no-store",
      },
    ),
  );
}

export async function refreshInvidiousTranscript(
  materialId: string,
): Promise<TimedMediaMaterial> {
  return unwrap(
    await apiFetch(
      apiUrl(
        `/api/video-learning/materials/${encodeURIComponent(materialId)}/transcript/refresh`,
      ),
      { method: "POST" },
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
        `/api/video-learning/materials/${encodeURIComponent(materialId)}/progress`,
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
    await apiFetch(apiUrl("/api/settings/video-learning"), {
      cache: "no-store",
    }),
  );
}

export async function saveVideoLearningSettings(
  settings: VideoLearningSettings,
): Promise<VideoLearningSettings> {
  return unwrap(
    await apiFetch(apiUrl("/api/settings/video-learning"), {
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
    await apiFetch(apiUrl("/api/settings/video-learning/test-invidious"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }),
  );
}

export interface InvidiousAccountStatus {
  connected: boolean;
  needs_reauthorization?: boolean;
}
export interface InvidiousVideo {
  hasCaptions?: boolean | null;
  videoId: string;
  title: string;
  author: string;
  lengthSeconds: number;
  videoThumbnails?: { url: string }[];
}
export interface InvidiousPlaylist {
  playlistId: string;
  title: string;
  videoCount: number;
  videos?: InvidiousVideo[];
}
export interface InvidiousCatalog {
  videos?: InvidiousVideo[];
}
export async function invidiousAccount(
  action: "status" | "authorize" | "disconnect",
) {
  return unwrap<InvidiousAccountStatus & { authorize_url?: string }>(
    await apiFetch(`/api/video-learning/invidious/account/${action}`, {
      method: action === "status" ? "GET" : "POST",
      cache: "no-store",
    }),
  );
}
export async function browseInvidious(
  kind: string,
  query: string,
  page: number,
  playlistId: string,
  signal: AbortSignal,
) {
  if (kind === "popular" || kind === "trending") {
    const feed = await unwrap<{
      items: {
        video_id: string;
        has_captions?: boolean | null;
        title: string;
        author: string;
        duration_seconds: number;
        thumbnail_url: string;
      }[];
      reason: string;
    }>(
      await apiFetch(`/api/video-learning/invidious/home?tab=${kind}`, {
        signal,
        cache: "no-store",
      }),
    );
    if (feed.reason === "unavailable")
      throw new Error(
        "Invidious could not load videos. Please retry or check the instance.",
      );
    return {
      videos: feed.items.map(item => ({
        videoId: item.video_id,
        hasCaptions: item.has_captions,
        title: item.title,
        author: item.author,
        lengthSeconds: item.duration_seconds,
        videoThumbnails: [{ url: item.thumbnail_url }],
      })),
    };
  }
  const params = new URLSearchParams({
    q: query,
    page: String(page),
    playlist_id: playlistId,
  });
  return unwrap<InvidiousVideo[] | InvidiousPlaylist[] | InvidiousCatalog>(
    await apiFetch(`/api/video-learning/invidious/browse/${kind}?${params}`, {
      signal,
      cache: "no-store",
    }),
  );
}

export async function captionStatus(videoIds: string[], signal: AbortSignal) {
  return unwrap<Record<string, { ready: boolean; language: string }>>(
    await apiFetch("/api/video-learning/captions/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_ids: videoIds.slice(0, 48) }),
      signal,
      cache: "no-store",
    }),
  );
}
