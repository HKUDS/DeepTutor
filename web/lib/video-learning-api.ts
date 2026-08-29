import { apiFetch, apiUrl } from "@/lib/api";

export interface TimedCue {
  start: number;
  end: number;
  text: string;
}

export interface TimedSegment extends TimedCue {
  locator: number;
}

export interface TimedMediaFormat {
  format_id: string;
  mime_type: string;
  quality: string;
  content_length: number;
  stream_url: string;
}

export interface TimedMediaMaterial {
  version: number;
  type: "timed_media";
  material_id: string;
  source: {
    provider: "youtube";
    video_id: string;
    url: string;
    entry_time_seconds: number;
    duration_seconds: number;
  };
  metadata: {
    title: string;
    author: string;
    duration_seconds: number;
    chapters: Array<{ start: number; title: string }>;
  };
  transcript: {
    language: string;
    source: string;
    cues: TimedCue[];
    fetch?: { status: string; error_code?: string | null };
  };
  segments: TimedSegment[];
  playback: {
    formats: Record<string, TimedMediaFormat>;
    official_url: string;
  };
  learning: {
    last_position: number;
    cumulative_played_seconds?: number;
    invidious_history_synced?: boolean;
    notes: VideoNote[];
    marks?: VideoLearningMark[];
    kb_publish?: KbPublishState | null;
  };
}

export interface VideoNote {
  note_id: string;
  text: string;
  time_seconds: number;
  quote?: string;
  created_at: string;
}

export type VideoMarkKind = "key_point" | "question" | "review";
export type VideoMarkAuthor = "user" | "assistant";

export interface VideoLearningMark {
  mark_id: string;
  kind: VideoMarkKind;
  start_seconds: number;
  end_seconds: number;
  start_locator: number;
  end_locator: number;
  quote: string;
  note: string;
  author: VideoMarkAuthor;
  source?: "immersive" | "remote_phone";
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  reviewed_at?: string;
}

export interface VideoMarkSuggestion {
  kind: VideoMarkKind;
  start_seconds: number;
  end_seconds: number;
  start_locator: number;
  end_locator: number;
  quote: string;
  note: string;
  author: VideoMarkAuthor;
}

export interface KbPublishState {
  kb_name: string;
  kb_id?: string;
  path: string;
  title?: string;
  content_hash: string;
  published_at: string;
  indexed_count?: number;
}

export interface PublishVideoToKbResult {
  material: TimedMediaMaterial;
  kb_name: string;
  kb_id?: string;
  path: string;
  content_hash: string;
  updated: boolean;
  published_at: string;
  kb_publish: KbPublishState | null;
}

export interface CreateBookFromVideoResult {
  book: { id: string; title?: string; status?: string };
  proposal: Record<string, unknown>;
  material: TimedMediaMaterial;
  kb_publish: KbPublishState | null;
}

export interface InvidiousStatus {
  configured: boolean;
  connected: boolean;
  invidious_base_url: string;
  invidious_public_base_url: string;
  user_preferences: { default_home?: string } | null;
}

export interface InvidiousFeedItem {
  video_id: string;
  title: string;
  author: string;
  author_id: string;
  duration_seconds: number;
  thumbnail_url: string;
  view_count: number;
  published_text: string;
  watched: boolean;
}

export interface InvidiousHomeFeed {
  connected: boolean;
  default_home: string;
  current_tab: string;
  tabs: string[];
  items: InvidiousFeedItem[];
  invidious_public_base_url: string;
}

async function unwrap<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      typeof payload?.detail === "string"
        ? payload.detail
        : "The video learning request failed."
    );
  }
  return payload as T;
}

export async function resolveVideoLearning(url: string): Promise<TimedMediaMaterial> {
  return unwrap(
    await apiFetch(apiUrl("/api/v1/video-learning/resolve"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    })
  );
}

export async function getVideoLearningMaterial(materialId: string): Promise<TimedMediaMaterial> {
  return unwrap(
    await apiFetch(apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}`), {
      cache: "no-store",
    })
  );
}

export async function connectYouTubeSession(materialId = ""): Promise<{ connection: string; helper_available: boolean }> {
  return unwrap(
    await apiFetch(apiUrl("/api/v1/video-learning/youtube-session/connect"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ material_id: materialId }),
    })
  );
}

export async function requestSubtitlePrefetch(materialId: string): Promise<void> {
  await unwrap(
    await apiFetch(apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/subtitle-prefetch`), {
      method: "POST",
    })
  );
}

export async function saveVideoPosition(materialId: string, timeSeconds: number): Promise<void> {
  await unwrap(
    await apiFetch(apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/position`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ time_seconds: timeSeconds }),
    })
  );
}

export async function recordWatchProgress(
  materialId: string,
  timeSeconds: number,
  cumulativePlayedSeconds: number
): Promise<{ time_seconds: number; cumulative_played_seconds: number; synced_to_invidious: boolean }> {
  return unwrap(
    await apiFetch(apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/watch-progress`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        time_seconds: timeSeconds,
        cumulative_played_seconds: cumulativePlayedSeconds,
      }),
    })
  );
}

export function timedMediaStreamUrl(materialId: string, formatId: string): string {
  return apiUrl(
    `/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/stream/${encodeURIComponent(formatId)}`
  );
}

export function timedMediaSubtitleUrl(materialId: string): string {
  return apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/subtitles.vtt`);
}

export async function createTranscriptJob(
  materialId: string,
  language = ""
): Promise<{ job_id: string; status: string }> {
  return unwrap(
    await apiFetch(apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/transcript-jobs`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language }),
    })
  );
}

export async function getTranscriptJob(
  jobId: string
): Promise<{ job_id: string; status: string; progress?: number; error?: string }> {
  return unwrap(
    await apiFetch(apiUrl(`/api/v1/video-learning/transcript-jobs/${encodeURIComponent(jobId)}`), {
      cache: "no-store",
    })
  );
}

export async function addVideoNote(
  materialId: string,
  text: string,
  timeSeconds: number,
  quote = ""
): Promise<VideoNote> {
  return unwrap(
    await apiFetch(apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/notes`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, time_seconds: timeSeconds, quote }),
    })
  );
}

export async function getInvidiousStatus(): Promise<InvidiousStatus> {
  return unwrap(
    await apiFetch(apiUrl("/api/v1/video-learning/invidious/status"), { cache: "no-store" })
  );
}

export async function getInvidiousAuthorizeUrl(callbackBase?: string): Promise<string> {
  const query = callbackBase ? `?callback_base=${encodeURIComponent(callbackBase)}` : "";
  const res = await unwrap<{ authorize_url: string }>(
    await apiFetch(apiUrl(`/api/v1/video-learning/invidious/authorize${query}`), { cache: "no-store" })
  );
  return res.authorize_url;
}

export async function disconnectInvidious(): Promise<void> {
  await unwrap(
    await apiFetch(apiUrl("/api/v1/video-learning/invidious/disconnect"), { method: "POST" })
  );
}

export async function getInvidiousHome(tab?: string): Promise<InvidiousHomeFeed> {
  const query = tab ? `?tab=${encodeURIComponent(tab)}` : "";
  return unwrap(
    await apiFetch(apiUrl(`/api/v1/video-learning/invidious/home${query}`), { cache: "no-store" })
  );
}

export async function createVideoMark(
  materialId: string,
  payload: {
    kind: VideoMarkKind;
    start_seconds: number;
    end_seconds: number;
    start_locator?: number;
    end_locator?: number;
    quote?: string;
    note?: string;
    author?: VideoMarkAuthor;
  }
): Promise<VideoLearningMark> {
  return unwrap(
    await apiFetch(apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/marks`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export async function patchVideoMark(
  materialId: string,
  markId: string,
  payload: Partial<{
    kind: VideoMarkKind;
    start_seconds: number;
    end_seconds: number;
    start_locator: number;
    end_locator: number;
    quote: string;
    note: string;
    reviewed: boolean;
  }>
): Promise<VideoLearningMark> {
  return unwrap(
    await apiFetch(
      apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/marks/${encodeURIComponent(markId)}`),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    )
  );
}

export async function deleteVideoMark(materialId: string, markId: string): Promise<void> {
  await unwrap(
    await apiFetch(
      apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/marks/${encodeURIComponent(markId)}`),
      { method: "DELETE" }
    )
  );
}

export async function suggestVideoMarks(
  materialId: string,
  timeSeconds: number
): Promise<VideoMarkSuggestion[]> {
  const payload = await unwrap<{ suggestions: VideoMarkSuggestion[] }>(
    await apiFetch(
      apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/mark-suggestions`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ time_seconds: timeSeconds }),
      }
    )
  );
  return payload.suggestions || [];
}

export async function publishVideoToKb(
  materialId: string,
  kbName = "default"
): Promise<PublishVideoToKbResult> {
  return unwrap(
    await apiFetch(
      apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/publish-to-kb`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kb_name: kbName }),
      }
    )
  );
}

export async function createBookFromVideo(
  materialId: string,
  payload: {
    kb_name?: string;
    user_intent?: string;
    language?: string;
    depth?: string;
    publish?: boolean;
  } = {}
): Promise<CreateBookFromVideoResult> {
  return unwrap(
    await apiFetch(
      apiUrl(`/api/v1/video-learning/materials/${encodeURIComponent(materialId)}/create-book`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kb_name: payload.kb_name || "default",
          user_intent: payload.user_intent || "",
          language: payload.language || "en",
          depth: payload.depth || "standard",
          publish: payload.publish !== false,
        }),
      }
    )
  );
}
